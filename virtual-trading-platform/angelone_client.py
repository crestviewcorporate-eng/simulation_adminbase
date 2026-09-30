import logging
import os
import threading
import time
from typing import Any, Dict, Optional
import pyotp
import redis
from dotenv import load_dotenv
from SmartApi import SmartConnect
from SmartApi.smartExceptions import DataException

from db import get_db

load_dotenv()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom Exceptions & Constants
# ---------------------------------------------------------------------------
class LTPFetchError(Exception):
    """Raised when fetching live market price (LTP) from AngelOne fails."""
    pass


class BadSymbolTokenError(LTPFetchError):
    """Raised when an instrument token is invalid, unrecognized, or expired at the broker."""
    pass


STALE_MAX_AGE_SECONDS: float = float(os.getenv("STALE_MAX_AGE_SECONDS", "15.0"))


# ---------------------------------------------------------------------------
# Rate Limiter & Caches
# ---------------------------------------------------------------------------
_redis_client: Optional[redis.Redis] = None
_memory_cache: Dict[str, Dict[str, Any]] = {}
_session_cache: Dict[str, Any] = {}
_api_lock = threading.Lock()
_last_api_request_time: float = 0.0
MIN_API_INTERVAL: float = 1.0   # Max 1 request/sec — safe ceiling for AngelOne rate limits


def get_redis_client() -> Optional[redis.Redis]:
    global _redis_client
    if _redis_client is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        try:
            r = redis.from_url(redis_url, decode_responses=True, socket_timeout=2)
            r.ping()
            _redis_client = r
            logger.info("Connected to Redis cache.")
        except Exception as e:
            logger.warning(f"Redis cache unavailable at {redis_url}: {e}. Running with In-Memory cache.")
            _redis_client = None
    return _redis_client


# ---------------------------------------------------------------------------
# AngelOne SmartAPI Client
# ---------------------------------------------------------------------------
class AngelOneClient:
    """Manages authentication and live market data retrieval via AngelOne SmartAPI."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        client_id: Optional[str] = None,
        password: Optional[str] = None,
        totp_secret: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("ANGELONE_API_KEY") or os.getenv("SMART_API_KEY", "")
        self.client_id = client_id or os.getenv("ANGELONE_CLIENT_ID") or os.getenv("SMART_CLIENT_ID", "")
        self.password = password or os.getenv("ANGELONE_PASSWORD") or os.getenv("SMART_PASSWORD", "")
        self.totp_secret = totp_secret or os.getenv("ANGELONE_TOTP_SECRET") or os.getenv("SMART_TOTP_SECRET", "")

        self.smart_api: Optional[SmartConnect] = None
        self.auth_token: Optional[str] = None
        self.feed_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self._last_login_time: float = 0.0

    def _sanitize_token(self, token: Optional[str]) -> Optional[str]:
        """Strip redundant Bearer prefixes to prevent SmartConnect double-Bearer headers."""
        if not token:
            return token
        t = token.strip()
        while t.startswith("Bearer "):
            t = t[7:].strip()
        return t

    def login(self, force_refresh: bool = False) -> bool:
        """Authenticate with AngelOne using client credentials and TOTP."""
        if not self.api_key or not self.client_id or not self.password or not self.totp_secret:
            raise LTPFetchError(
                "AngelOne credentials missing (ANGELONE_API_KEY, ANGELONE_CLIENT_ID, "
                "ANGELONE_PASSWORD, ANGELONE_TOTP_SECRET are required)."
            )

        now = time.time()
        if force_refresh:
            self.auth_token = None
            self.smart_api = None
            _session_cache.clear()
            r = get_redis_client()
            if r:
                try:
                    r.delete(f"angelone:session:{self.client_id}:jwt")
                    r.delete(f"angelone:session:{self.client_id}:feed")
                except Exception:
                    pass
        elif self.smart_api and self.auth_token and (now - self._last_login_time) < 3600:
            return True

        # Check in-memory session cache first
        if not force_refresh and _session_cache.get("jwt") and _session_cache.get("feed"):
            if (now - _session_cache.get("time", 0)) < 43200:  # 12 hours
                self.auth_token = _session_cache["jwt"]
                self.feed_token = _session_cache["feed"]
                self.smart_api = SmartConnect(api_key=self.api_key, timeout=15)
                self.smart_api.setAccessToken(self.auth_token)
                self.smart_api.setFeedToken(self.feed_token)
                self._last_login_time = now
                logger.info("Loaded AngelOne session from in-memory cache.")
                return True

        # Check Redis cached session token
        r = get_redis_client()
        session_key = f"angelone:session:{self.client_id}"
        if not force_refresh and r:
            try:
                cached_jwt = self._sanitize_token(r.get(f"{session_key}:jwt"))
                cached_feed = r.get(f"{session_key}:feed")
                if cached_jwt and cached_feed:
                    self.auth_token = cached_jwt
                    self.feed_token = cached_feed
                    self.smart_api = SmartConnect(api_key=self.api_key, timeout=15)
                    self.smart_api.setAccessToken(self.auth_token)
                    self.smart_api.setFeedToken(self.feed_token)
                    self._last_login_time = now
                    _session_cache["jwt"] = cached_jwt
                    _session_cache["feed"] = cached_feed
                    _session_cache["time"] = now
                    logger.info("Loaded AngelOne session from Redis cache.")
                    return True
            except Exception as e:
                logger.warning(f"Could not read AngelOne session from Redis: {e}")

        with _api_lock:
            global _last_api_request_time
            now = time.time()
            elapsed = now - _last_api_request_time
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)
            _last_api_request_time = time.time()

            logger.info(f"Authenticating with AngelOne SmartAPI for client: {self.client_id}...")
            try:
                totp = pyotp.TOTP(self.totp_secret).now()
                smart_connect = SmartConnect(api_key=self.api_key, timeout=15)
                session_data = smart_connect.generateSession(self.client_id, self.password, totp)

                if not session_data or not session_data.get("status"):
                    error_msg = session_data.get("message", "Unknown error during session generation")
                    raise LTPFetchError(f"AngelOne login failed: {error_msg}")

                data = session_data.get("data", {})
                raw_jwt = self._sanitize_token(data.get("jwtToken"))
                self.auth_token = raw_jwt
                self.feed_token = data.get("feedToken")
                self.refresh_token = data.get("refreshToken")
                
                smart_connect.setAccessToken(raw_jwt)
                smart_connect.setFeedToken(self.feed_token)
                if self.refresh_token:
                    smart_connect.setRefreshToken(self.refresh_token)

                self.smart_api = smart_connect
                self._last_login_time = now

                _session_cache["jwt"] = raw_jwt
                _session_cache["feed"] = self.feed_token
                _session_cache["time"] = now

                # Cache in Redis with ~22 hours TTL
                if r and self.auth_token and self.feed_token:
                    try:
                        pipe = r.pipeline()
                        pipe.set(f"{session_key}:jwt", self.auth_token, ex=79200)
                        pipe.set(f"{session_key}:feed", self.feed_token, ex=79200)
                        pipe.execute()
                    except Exception as e:
                        logger.warning(f"Failed to cache AngelOne session to Redis: {e}")

                logger.info("AngelOne SmartAPI authentication successful.")
                return True

            except LTPFetchError:
                raise
            except Exception as e:
                raise LTPFetchError(f"AngelOne login exception: {str(e)}") from e

    def _fetch_ltp_from_api(self, exchange: str, tradingsymbol: str, symboltoken: str, retry_on_auth: bool = True) -> float:
        """Raw API invocation to get LTP from SmartConnect with rate limiting, timeouts, and session re-auth."""
        if not self.smart_api or not self.auth_token:
            self.login()

        with _api_lock:
            global _last_api_request_time
            now = time.time()
            elapsed = now - _last_api_request_time
            if elapsed < MIN_API_INTERVAL:
                time.sleep(MIN_API_INTERVAL - elapsed)
            _last_api_request_time = time.time()

            try:
                res = self.smart_api.ltpData(exchange, tradingsymbol, symboltoken)
            except Exception as net_err:
                err_str = str(net_err).lower()
                if "time" in err_str or "connection" in err_str:
                    logger.warning(f"SmartAPI network timeout/reset for {tradingsymbol} ({symboltoken}): {net_err}. Retrying once in 1s...")
                    time.sleep(1.0)
                    res = self.smart_api.ltpData(exchange, tradingsymbol, symboltoken)
                else:
                    raise

        # Check for Session Expiry (AG8001 / Invalid Token)
        if isinstance(res, dict):
            error_code = str(res.get("errorCode", "") or res.get("errorcode", "")).upper()
            msg = str(res.get("message", "")).lower()
            if error_code in ("AG8001", "AG8002", "AG8003") or "invalid token" in msg or "session expired" in msg:
                if retry_on_auth:
                    logger.warning(f"AngelOne session expired ({error_code}: {msg}). Re-authenticating and retrying...")
                    self.login(force_refresh=True)
                    return self._fetch_ltp_from_api(exchange, tradingsymbol, symboltoken, retry_on_auth=False)

        if not res or not res.get("status"):
            msg = res.get("message", "No response or status False") if isinstance(res, dict) else str(res)
            err_code = res.get("errorcode", "") or res.get("errorCode", "") if isinstance(res, dict) else ""
            msg_lower = msg.lower()
            if any(k in msg_lower for k in ("ab4046", "symbol token not found", "token not found", "bad/expired token", "invalid symbol")):
                raise BadSymbolTokenError(f"Bad/expired symbol token {symboltoken} for {tradingsymbol}: {msg} (code: {err_code})")
            raise ValueError(f"LTP API error response: {msg} (code: {err_code})")

        data = res.get("data", {})
        if "ltp" not in data or data["ltp"] is None:
            raise ValueError(f"Missing 'ltp' in SmartAPI response data: {res}")

        return float(data["ltp"])

    def get_ltp_with_meta(
        self,
        exchange: str,
        tradingsymbol: str,
        symboltoken: str,
        max_age_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Fetch real-time LTP with metadata {price, fetched_at, source: 'live'|'cache'}.

        Serves cached price only if fetched within max_age_seconds (or STALE_MAX_AGE_SECONDS, default 15s).
        Otherwise raises LTPFetchError.
        """
        cache_key = f"ltp:{exchange}:{symboltoken}"
        now = time.time()
        max_stale = max_age_seconds if max_age_seconds is not None else STALE_MAX_AGE_SECONDS

        # ── Step 1: In-Memory Cache (fresh within 10s TTL) ─────────────────────
        if cache_key in _memory_cache:
            entry = _memory_cache[cache_key]
            age = now - entry["time"]
            if age < 10.0:
                logger.debug(f"[MEM CACHE HIT] {tradingsymbol} ({symboltoken}) -> ₹{entry['price']} (age {age:.1f}s)")
                return {
                    "price": float(entry["price"]),
                    "fetched_at": float(entry["time"]),
                    "source": "cache",
                }

        # ── Step 2: Redis Cache (fresh within 10s TTL) ─────────────────────────
        r = get_redis_client()
        if r:
            try:
                cached_price = r.get(cache_key)
                if cached_price is not None:
                    p = float(cached_price)
                    _memory_cache[cache_key] = {"price": p, "time": now}
                    logger.debug(f"[REDIS CACHE HIT] {tradingsymbol} ({symboltoken}) -> ₹{p}")
                    return {
                        "price": p,
                        "fetched_at": now,
                        "source": "cache",
                    }
            except Exception as e:
                logger.debug(f"Redis get error: {e}")

        # ── Step 3: Live Fetch from Broker ─────────────────────────────────────
        try:
            price = self._fetch_ltp_from_api(exchange, tradingsymbol, symboltoken)
            logger.info(f"[LIVE FETCH] {tradingsymbol} ({symboltoken}) -> ₹{price}")

            # Populate caches (10s TTL in Redis)
            _memory_cache[cache_key] = {"price": price, "time": now}
            if r:
                try:
                    r.set(cache_key, price, ex=10)
                except Exception:
                    pass

            return {
                "price": price,
                "fetched_at": now,
                "source": "live",
            }

        except Exception as fetch_err:
            err_str = str(fetch_err).lower()
            is_bad_symbol = isinstance(fetch_err, BadSymbolTokenError) or any(
                k in err_str for k in ("ab4046", "symbol token not found", "token not found", "bad/expired token")
            )

            if is_bad_symbol:
                raise BadSymbolTokenError(
                    f"Bad/expired symbol token {symboltoken} for {tradingsymbol}: {fetch_err}"
                ) from fetch_err

            # Step 4: Stale cache fallback strictly within STALE_MAX_AGE_SECONDS
            if cache_key in _memory_cache:
                entry = _memory_cache[cache_key]
                stale_age = now - entry["time"]
                if stale_age <= max_stale:
                    stale_price = float(entry["price"])
                    logger.warning(
                        f"[STALE CACHE SERVE] {tradingsymbol}: serving last known ₹{stale_price} "
                        f"(cached {stale_age:.1f}s ago <= {max_stale}s). Error: {fetch_err}"
                    )
                    return {
                        "price": stale_price,
                        "fetched_at": float(entry["time"]),
                        "source": "cache",
                    }

            raise LTPFetchError(
                f"Failed to fetch live LTP from AngelOne for {exchange}:{tradingsymbol} ({symboltoken}): {fetch_err}"
            ) from fetch_err

    def get_ltp(
        self,
        exchange: str,
        tradingsymbol: str,
        symboltoken: str,
        max_age_seconds: Optional[float] = None,
    ) -> float:
        """Fetch real-time LTP with multi-tiered caching and strict freshness ceiling.
        Returns float price from live broker quote or fresh cache <= STALE_MAX_AGE_SECONDS.
        Raises LTPFetchError if live quote fails and cache is absent or older than STALE_MAX_AGE_SECONDS.
        """
        meta = self.get_ltp_with_meta(
            exchange=exchange,
            tradingsymbol=tradingsymbol,
            symboltoken=symboltoken,
            max_age_seconds=max_age_seconds,
        )
        return float(meta["price"])

    @staticmethod
    async def lookup_instrument(
        symbol: str,
        segment: Optional[str] = None,
        expiry: Optional[str] = None,
        strike: Optional[float] = None,
        option_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Lookup instrument mapping (exchange, symboltoken, tradingsymbol, lot_size) from MongoDB."""
        database = get_db()
        instruments_coll = database["instruments"]

        query: Dict[str, Any] = {"symbol": symbol.upper()}
        if segment:
            query["segment"] = segment.lower()
        if expiry:
            query["expiry"] = expiry
        if strike is not None:
            query["strike"] = float(strike)
        if option_type:
            query["option_type"] = option_type.upper()

        doc = await instruments_coll.find_one(query)
        if not doc:
            doc = await instruments_coll.find_one({"tradingsymbol": symbol.upper()})

        if doc:
            return {
                "exchange": doc.get("exchange", "NSE"),
                "symboltoken": str(doc.get("symboltoken")),
                "tradingsymbol": doc.get("tradingsymbol", symbol),
                "lot_size": doc.get("lot_size", 1),
                "segment": doc.get("segment"),
                "strike": doc.get("strike"),
                "option_type": doc.get("option_type"),
                "expiry": doc.get("expiry"),
            }
        return None


# Module-level singleton instance
angel_client = AngelOneClient()
