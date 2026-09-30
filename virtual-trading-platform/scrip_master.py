"""Scrip Master & Contract Metadata Service
Downloads and indexes official Angel One Scrip Master JSON.
Handles:
  1. Auto-detecting official lot sizes for all instruments and segments.
  2. Nearest ATM strike calculation (math.floor for CE, math.ceil for PE).
  3. Expiry categorization (Running / Current, Next, Upcoming) with IST cutoff.
  4. Instant contract resolution (token, tradingsymbol, exchange, lot size, pnl_multiplier).
"""
import os
import json
import math
import time
import logging
import requests
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("virtual_trading_platform.scrip_master")

SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "data")
CACHE_FILE = os.path.join(CACHE_DIR, "scrip_master.json")
CACHE_MAX_AGE_SECONDS = 86400  # 24 hours

INDEX_CONFIGS = {
    "NIFTY": {
        "spot": {"exchange": "NSE", "token": "99926000", "tradingsymbol": "Nifty 50"},
        "strike_step": 50,
        "nfo_name": "NIFTY",
        "default_lot": 65,
    },
    "BANKNIFTY": {
        "spot": {"exchange": "NSE", "token": "99926009", "tradingsymbol": "Nifty Bank"},
        "strike_step": 100,
        "nfo_name": "BANKNIFTY",
        "default_lot": 30,
    },
    "SENSEX": {
        "spot": {"exchange": "BSE", "token": "99919000", "tradingsymbol": "SENSEX"},
        "strike_step": 100,
        "nfo_name": "SENSEX",
        "exch_seg": "BFO",
        "default_lot": 20,
    },
    "FINNIFTY": {
        "spot": {"exchange": "NSE", "token": "99926037", "tradingsymbol": "Nifty Fin Services"},
        "strike_step": 50,
        "nfo_name": "FINNIFTY",
        "default_lot": 65,
    },
    "MIDCPNIFTY": {
        "spot": {"exchange": "NSE", "token": "99926074", "tradingsymbol": "NIFTY MID SELECT"},
        "strike_step": 25,
        "nfo_name": "MIDCPNIFTY",
        "default_lot": 120,
    },
}

COMMODITY_CONFIGS: Dict[str, Dict[str, Any]] = {
    # Pre-filled & verified against Scrip Master lot sizes
    "GOLD": {
        "name": "GOLD",
        "display_name": "Gold",
        "exch_seg": "MCX",
        "fut_type": "FUTCOM",
        "quote_unit": "₹/10g",
        "pnl_multiplier_per_lot": 100,
        "enabled": True,
        "default_lot": 1,
    },
    "GOLDM": {
        "name": "GOLDM",
        "display_name": "Gold Mini",
        "exch_seg": "MCX",
        "fut_type": "FUTCOM",
        "quote_unit": "₹/10g",
        "pnl_multiplier_per_lot": 10,
        "enabled": True,
        "default_lot": 100,
    },
    "SILVER": {
        "name": "SILVER",
        "display_name": "Silver",
        "exch_seg": "MCX",
        "fut_type": "FUTCOM",
        "quote_unit": "₹/1kg",
        "pnl_multiplier_per_lot": 30,
        "enabled": True,
        "default_lot": 30,
    },
    "SILVERM": {
        "name": "SILVERM",
        "display_name": "Silver Mini",
        "exch_seg": "MCX",
        "fut_type": "FUTCOM",
        "quote_unit": "₹/1kg",
        "pnl_multiplier_per_lot": 5,
        "enabled": True,
        "default_lot": 5,
    },
    "CRUDEOIL": {
        "name": "CRUDEOIL",
        "display_name": "Crude Oil",
        "exch_seg": "MCX",
        "fut_type": "FUTCOM",
        "quote_unit": "₹/bbl",
        "pnl_multiplier_per_lot": 100,
        "enabled": True,
        "default_lot": 100,
    },
    "NATURALGAS": {
        "name": "NATURALGAS",
        "display_name": "Natural Gas",
        "exch_seg": "MCX",
        "fut_type": "FUTCOM",
        "quote_unit": "₹/mmBtu",
        "pnl_multiplier_per_lot": 1250,
        "enabled": True,
        "default_lot": 1250,
    },
    # Other commodities - disabled and multiplier blank until verified against official MCX contract spec
    "GOLDPETAL": {
        "name": "GOLDPETAL",
        "display_name": "Gold Petal",
        "exch_seg": "MCX",
        "fut_type": "FUTCOM",
        "quote_unit": "₹/1g",
        "pnl_multiplier_per_lot": None,
        "enabled": False,
        "default_lot": 1,
    },
    "SILVERMIC": {
        "name": "SILVERMIC",
        "display_name": "Silver Micro",
        "exch_seg": "MCX",
        "fut_type": "FUTCOM",
        "quote_unit": "₹/1kg",
        "pnl_multiplier_per_lot": None,
        "enabled": False,
        "default_lot": 1,
    },
    "CRUDEOILM": {
        "name": "CRUDEOILM",
        "display_name": "Crude Oil Mini",
        "exch_seg": "MCX",
        "fut_type": "FUTCOM",
        "quote_unit": "₹/bbl",
        "pnl_multiplier_per_lot": None,
        "enabled": False,
        "default_lot": 10,
    },
    "NATGASMINI": {
        "name": "NATGASMINI",
        "display_name": "Natural Gas Mini",
        "exch_seg": "MCX",
        "fut_type": "FUTCOM",
        "quote_unit": "₹/mmBtu",
        "pnl_multiplier_per_lot": None,
        "enabled": False,
        "default_lot": 250,
    },
    "COPPER": {
        "name": "COPPER",
        "display_name": "Copper",
        "exch_seg": "MCX",
        "fut_type": "FUTCOM",
        "quote_unit": "₹/1kg",
        "pnl_multiplier_per_lot": None,
        "enabled": False,
        "default_lot": 2500,
    },
    "ZINC": {
        "name": "ZINC",
        "display_name": "Zinc",
        "exch_seg": "MCX",
        "fut_type": "FUTCOM",
        "quote_unit": "₹/1kg",
        "pnl_multiplier_per_lot": None,
        "enabled": False,
        "default_lot": 5000,
    },
    "ALUMINIUM": {
        "name": "ALUMINIUM",
        "display_name": "Aluminium",
        "exch_seg": "MCX",
        "fut_type": "FUTCOM",
        "quote_unit": "₹/1kg",
        "pnl_multiplier_per_lot": None,
        "enabled": False,
        "default_lot": 5000,
    },
    "LEAD": {
        "name": "LEAD",
        "display_name": "Lead",
        "exch_seg": "MCX",
        "fut_type": "FUTCOM",
        "quote_unit": "₹/1kg",
        "pnl_multiplier_per_lot": None,
        "enabled": False,
        "default_lot": 5000,
    },
    "NICKEL": {
        "name": "NICKEL",
        "display_name": "Nickel",
        "exch_seg": "MCX",
        "fut_type": "FUTCOM",
        "quote_unit": "₹/1kg",
        "pnl_multiplier_per_lot": None,
        "enabled": False,
        "default_lot": 1500,
    },
}


class ScripMasterService:
    def __init__(self):
        self._instruments: List[Dict[str, Any]] = []
        self._by_symbol_segment: Dict[str, List[Dict[str, Any]]] = {}
        self._is_loaded = False

    def ensure_loaded(self) -> None:
        """Loads or downloads the scrip master JSON."""
        if self._is_loaded and self._instruments:
            return

        os.makedirs(CACHE_DIR, exist_ok=True)
        data = None

        # Check if local cache file is recent
        if os.path.exists(CACHE_FILE):
            try:
                mtime = os.path.getmtime(CACHE_FILE)
                if (time.time() - mtime) < CACHE_MAX_AGE_SECONDS:
                    logger.info("Loading Scrip Master from local cache...")
                    with open(CACHE_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read cached Scrip Master: {e}")

        if not data:
            logger.info("Downloading official Angel One Scrip Master JSON...")
            try:
                resp = requests.get(SCRIP_MASTER_URL, timeout=45)
                if resp.status_code == 200:
                    data = resp.json()
                    with open(CACHE_FILE, "w", encoding="utf-8") as f:
                        json.dump(data, f)
                    logger.info(f"Downloaded and cached {len(data):,} instruments.")
                else:
                    logger.error(f"Failed to download Scrip Master, status {resp.status_code}")
            except Exception as err:
                logger.error(f"Scrip Master download exception: {err}")

        if data:
            self._instruments = data
            self._build_indexes()
            self._is_loaded = True
        else:
            logger.warning("Scrip Master could not be loaded, using fallback definitions.")

    def _build_indexes(self) -> None:
        """Build fast in-memory indexes for target indices and commodities."""
        self._by_symbol_segment.clear()
        for item in self._instruments:
            name = item.get("name", "").upper()
            if name in INDEX_CONFIGS or name in COMMODITY_CONFIGS:
                exch_seg = item.get("exch_seg", "")
                itype = item.get("instrumenttype", "")
                key = f"{name}:{exch_seg}:{itype}"
                if key not in self._by_symbol_segment:
                    self._by_symbol_segment[key] = []
                self._by_symbol_segment[key].append(item)

    def get_instrument_type(self, symbol: str) -> str:
        """Determines if a symbol is INDEX or MCX commodity."""
        sym = symbol.upper()
        if sym in COMMODITY_CONFIGS:
            return "MCX"
        return "INDEX"

    def get_pnl_multiplier(self, symbol: str, lot_size: Optional[int] = None) -> Optional[float]:
        """Returns the P&L multiplier per lot.
        For commodities: configured pnl_multiplier_per_lot (or None if unverified).
        For index/cash: equals lot_size.
        """
        sym = symbol.upper()
        if sym in COMMODITY_CONFIGS:
            mult = COMMODITY_CONFIGS[sym].get("pnl_multiplier_per_lot")
            return float(mult) if mult is not None else None
        return float(lot_size if lot_size is not None else self.get_lot_size(sym))

    def get_strike_step(self, symbol: str) -> int:
        """Returns the index strike step for nearest strike math."""
        sym = symbol.upper()
        if sym in INDEX_CONFIGS:
            return INDEX_CONFIGS[sym]["strike_step"]
        return 50

    def calculate_atm_strike(self, symbol: str, spot_ltp: float, option_type: str) -> float:
        """
        Calculates nearest ATM / ITM strike:
          - CE: math.floor(spot / strike_step) * strike_step
          - PE: math.ceil(spot / strike_step) * strike_step
        """
        step = self.get_strike_step(symbol)
        if step <= 0:
            step = 50

        opt = (option_type or "CE").upper()
        if opt == "CE":
            return float(math.floor(spot_ltp / step) * step)
        else:
            return float(math.ceil(spot_ltp / step) * step)

    def get_spot_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Returns exchange, symboltoken, and tradingsymbol for the cash spot index.
        Note: MCX commodities have no spot feed; reference price is nearest future's LTP.
        """
        sym = symbol.upper()
        if sym in INDEX_CONFIGS:
            cfg = INDEX_CONFIGS[sym]["spot"]
            return {
                "symbol": sym,
                "exchange": cfg["exchange"],
                "symboltoken": cfg["token"],
                "tradingsymbol": cfg["tradingsymbol"],
                "segment": "cash",
                "lot_size": 1,
            }
        return None

    def get_expiries(self, symbol: str, segment: str = "option") -> List[Dict[str, Any]]:
        """Returns sorted active expiries categorized as Running / Current, Next, Upcoming.
        Uses market_calendar.contract_expired() in IST so contracts roll immediately after expiry-day close.
        """
        from market_calendar import contract_expired, now_ist

        self.ensure_loaded()
        sym = symbol.upper()
        is_commodity = sym in COMMODITY_CONFIGS

        if is_commodity:
            cfg = COMMODITY_CONFIGS[sym]
            exch = cfg.get("exch_seg", "MCX")
            itype = cfg.get("fut_type", "FUTCOM")
        else:
            cfg = INDEX_CONFIGS.get(sym, {})
            exch = cfg.get("exch_seg", "NFO" if sym != "SENSEX" else "BFO")
            itype = "OPTIDX" if segment.lower() == "option" else "FUTIDX"

        key = f"{sym}:{exch}:{itype}"
        contracts = self._by_symbol_segment.get(key, [])
        if not contracts:
            return []

        current_ist = now_ist()
        raw_expiries = list(set(c.get("expiry", "") for c in contracts if c.get("expiry")))

        valid_expiries: List[Tuple[datetime, str]] = []
        for e in raw_expiries:
            try:
                dt = datetime.strptime(e, "%d%b%Y")
                if not contract_expired(exchange=exch, expiry_date=dt.date(), current_time=current_ist):
                    valid_expiries.append((dt, e))
            except Exception:
                pass

        valid_expiries.sort(key=lambda x: x[0])

        result: List[Dict[str, Any]] = []
        for idx, (dt, exp_str) in enumerate(valid_expiries):
            formatted_date = dt.strftime("%d-%b-%Y")
            if idx == 0:
                label = f"{formatted_date} (Current / Running)"
                tag = "running"
            elif idx == 1:
                label = f"{formatted_date} (Next)"
                tag = "next"
            else:
                label = f"{formatted_date} (Upcoming)"
                tag = "upcoming"

            result.append({
                "expiry": exp_str,
                "label": label,
                "tag": tag,
                "formatted_date": formatted_date,
            })

        return result

    def get_strikes(self, symbol: str, expiry: Optional[str] = None) -> List[float]:
        """Returns sorted list of strike prices available for this symbol and expiry."""
        self.ensure_loaded()
        sym = symbol.upper()
        cfg = INDEX_CONFIGS.get(sym, {})
        exch = cfg.get("exch_seg", "NFO" if sym != "SENSEX" else "BFO")
        key = f"{sym}:{exch}:OPTIDX"
        contracts = self._by_symbol_segment.get(key, [])
        if not contracts:
            return []

        if isinstance(expiry, dict):
            expiry = expiry.get("expiry")
        if not expiry:
            exp_list = self.get_expiries(sym, "option")
            if exp_list:
                expiry = exp_list[0]["expiry"]

        strikes = set()
        for c in contracts:
            if not expiry or c.get("expiry") == expiry:
                try:
                    s_raw = float(c.get("strike", 0))
                    # AngelOne option strike is stored as strike * 100
                    s_val = s_raw / 100.0 if s_raw > 100000 else s_raw
                    if s_val > 0:
                        strikes.add(s_val)
                except Exception:
                    pass

        return sorted(list(strikes))

    def get_lot_size(self, symbol: str, segment: str = "option", expiry: Optional[str] = None) -> int:
        """Returns auto-detected official lot size from Scrip Master."""
        self.ensure_loaded()
        sym = symbol.upper()
        is_commodity = sym in COMMODITY_CONFIGS

        if is_commodity:
            cfg = COMMODITY_CONFIGS[sym]
            default_lot = cfg.get("default_lot", 1)
            exch = cfg.get("exch_seg", "MCX")
            itype = cfg.get("fut_type", "FUTCOM")
        else:
            cfg = INDEX_CONFIGS.get(sym, {})
            default_lot = cfg.get("default_lot", 25 if sym == "NIFTY" else 15)
            exch = cfg.get("exch_seg", "NFO" if sym != "SENSEX" else "BFO")
            itype = "OPTIDX" if segment.lower() == "option" else "FUTIDX"

        key = f"{sym}:{exch}:{itype}"
        contracts = self._by_symbol_segment.get(key, [])

        if contracts:
            if expiry:
                matching = [c for c in contracts if c.get("expiry") == expiry]
                if matching:
                    return int(matching[0].get("lotsize", default_lot))
            return int(contracts[0].get("lotsize", default_lot))

        return default_lot

    def find_contract(
        self,
        symbol: str,
        segment: str,
        expiry: Optional[str] = None,
        strike: Optional[float] = None,
        option_type: Optional[str] = None,
        spot_ltp: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Finds exact matching contract from Scrip Master.
        Auto-fills running expiry and nearest ATM strike if omitted.
        """
        self.ensure_loaded()
        sym = symbol.upper()
        seg = segment.lower()
        is_commodity = sym in COMMODITY_CONFIGS

        # 1. Cash / Spot
        if seg == "cash":
            if is_commodity:
                # MCX Commodities do not trade on Cash/Spot; fall back to active future
                return self.find_contract(symbol, "future", expiry=expiry)
            return self.get_spot_info(sym)

        # 2. Future Contract (INDEX or MCX COMMODITY)
        if seg == "future":
            if is_commodity:
                cfg = COMMODITY_CONFIGS[sym]
                exch = cfg.get("exch_seg", "MCX")
                itype = cfg.get("fut_type", "FUTCOM")
                inst_type = "MCX"
            else:
                cfg = INDEX_CONFIGS.get(sym, {})
                exch = cfg.get("exch_seg", "NFO" if sym != "SENSEX" else "BFO")
                itype = "FUTIDX"
                inst_type = "INDEX"

            key = f"{sym}:{exch}:{itype}"
            contracts = self._by_symbol_segment.get(key, [])
            if not contracts:
                return None

            if not expiry:
                expiries = self.get_expiries(sym, "future")
                expiry = expiries[0]["expiry"] if expiries else None

            matching = [c for c in contracts if (not expiry or c.get("expiry") == expiry)]
            if matching:
                target = matching[0]
                lot = int(target.get("lotsize", cfg.get("default_lot", 1 if is_commodity else 25)))
                pnl_mult = cfg.get("pnl_multiplier_per_lot", lot) if is_commodity else lot
                return {
                    "exchange": exch,
                    "symboltoken": str(target["token"]),
                    "tradingsymbol": target["symbol"],
                    "lot_size": lot,
                    "expiry": target.get("expiry"),
                    "segment": "future",
                    "symbol": sym,
                    "instrument_type": inst_type,
                    "pnl_multiplier_per_lot": pnl_mult,
                    "quote_unit": cfg.get("quote_unit", "₹/unit"),
                }
            return None

        # 3. Option Contract (INDEX only in Phase 1)
        if seg == "option":
            if is_commodity:
                # MCX options not enabled in Phase 1
                return None

            cfg = INDEX_CONFIGS.get(sym, {})
            exch = cfg.get("exch_seg", "NFO" if sym != "SENSEX" else "BFO")
            key = f"{sym}:{exch}:OPTIDX"
            contracts = self._by_symbol_segment.get(key, [])
            if not contracts:
                return None

            # Resolve Expiry (default to running expiry)
            if isinstance(expiry, dict):
                expiry = expiry.get("expiry")
            if not expiry:
                expiries = self.get_expiries(sym, "option")
                if expiries:
                    expiry = expiries[0]["expiry"]

            opt_type = (option_type or "CE").upper()

            # Resolve Strike (default to nearest ATM if spot_ltp is provided and strike is None)
            target_strike = strike
            if target_strike is None and spot_ltp is not None:
                target_strike = self.calculate_atm_strike(sym, spot_ltp, opt_type)

            for c in contracts:
                if expiry and c.get("expiry") != expiry:
                    continue
                if not c.get("symbol", "").endswith(opt_type):
                    continue

                if target_strike is not None:
                    s_raw = float(c.get("strike", 0))
                    s_val = s_raw / 100.0 if s_raw > 100000 else s_raw
                    if abs(s_val - float(target_strike)) > 0.01:
                        continue

                # Match found
                lot = int(c.get("lotsize", cfg.get("default_lot", 25)))
                return {
                    "exchange": exch,
                    "symboltoken": str(c["token"]),
                    "tradingsymbol": c["symbol"],
                    "lot_size": lot,
                    "expiry": c.get("expiry"),
                    "strike": target_strike,
                    "option_type": opt_type,
                    "segment": "option",
                    "symbol": sym,
                    "instrument_type": "INDEX",
                    "pnl_multiplier_per_lot": lot,
                    "quote_unit": "₹/unit",
                }

            # If target_strike had no exact match (e.g. stale strike from a different instrument),
            # fallback to nearest available strike for this expiry & option_type
            candidates = [
                c for c in contracts
                if (not expiry or c.get("expiry") == expiry) and c.get("symbol", "").endswith(opt_type)
            ]
            if candidates:
                if target_strike is not None:
                    def _strike_distance(c):
                        s_raw = float(c.get("strike", 0))
                        s_val = s_raw / 100.0 if s_raw > 100000 else s_raw
                        return abs(s_val - float(target_strike))
                    best_c = min(candidates, key=_strike_distance)
                else:
                    best_c = candidates[0]

                s_raw = float(best_c.get("strike", 0))
                s_val = s_raw / 100.0 if s_raw > 100000 else s_raw
                lot = int(best_c.get("lotsize", cfg.get("default_lot", 25)))
                return {
                    "exchange": exch,
                    "symboltoken": str(best_c["token"]),
                    "tradingsymbol": best_c["symbol"],
                    "lot_size": lot,
                    "expiry": best_c.get("expiry"),
                    "strike": s_val,
                    "option_type": opt_type,
                    "segment": "option",
                    "symbol": sym,
                    "instrument_type": "INDEX",
                    "pnl_multiplier_per_lot": lot,
                    "quote_unit": "₹/unit",
                }

        return None


# Global singleton instance
scrip_master = ScripMasterService()
