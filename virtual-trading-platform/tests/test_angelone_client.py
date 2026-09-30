import pytest
from unittest.mock import MagicMock, patch
from angelone_client import AngelOneClient, LTPFetchError


@pytest.mark.asyncio
async def test_instrument_lookup():
    client = AngelOneClient()
    
    # Test cash lookup
    nifty = await client.lookup_instrument(symbol="NIFTY", segment="cash")
    assert nifty is not None
    assert nifty["exchange"] == "NSE"
    assert nifty["tradingsymbol"] in ("NIFTY", "Nifty 50")
    assert nifty["lot_size"] == 1

    # Test future lookup
    banknifty_fut = await client.lookup_instrument(symbol="BANKNIFTY", segment="future")
    assert banknifty_fut is not None
    assert banknifty_fut["lot_size"] == 15
    assert banknifty_fut["exchange"] == "NFO"

    # Test option lookup
    sensex_opt = await client.lookup_instrument(symbol="SENSEX", segment="option", strike=74000.0, option_type="CE")
    assert sensex_opt is not None
    assert sensex_opt["lot_size"] == 10
    assert sensex_opt["option_type"] == "CE"


def test_ltp_cache_and_retry_mechanism():
    client = AngelOneClient(
        api_key="mock_key",
        client_id="mock_id",
        password="mock_pass",
        totp_secret="JBSWY3DPEHPK3PXP"
    )

    mock_smart_connect = MagicMock()
    mock_smart_connect.generateSession.return_value = {
        "status": True,
        "data": {
            "jwtToken": "mock_jwt",
            "feedToken": "mock_feed",
            "refreshToken": "mock_refresh"
        }
    }
    # First call fails, second call (after re-login) succeeds
    mock_smart_connect.ltpData.side_effect = [
        {"status": False, "message": "Session expired"},
        {"status": True, "data": {"ltp": 22450.75}}
    ]

    with patch("angelone_client.get_redis_client", return_value=None):
        with patch("angelone_client.SmartConnect", return_value=mock_smart_connect):
            client.login()
            price = client.get_ltp(exchange="NSE", tradingsymbol="NIFTY", symboltoken="token_test_1")
            assert price == 22450.75
            assert mock_smart_connect.ltpData.call_count == 2


def test_ltp_failure_raises_ltp_fetch_error():
    client = AngelOneClient(
        api_key="mock_key",
        client_id="mock_id",
        password="mock_pass",
        totp_secret="JBSWY3DPEHPK3PXP"
    )

    mock_smart_connect = MagicMock()
    mock_smart_connect.generateSession.return_value = {
        "status": True,
        "data": {"jwtToken": "mock_jwt", "feedToken": "mock_feed"}
    }
    # Both initial and retry fail
    mock_smart_connect.ltpData.return_value = {"status": False, "message": "Market quote server error"}

    with patch("angelone_client.get_redis_client", return_value=None):
        with patch("angelone_client.SmartConnect", return_value=mock_smart_connect):
            client.login()
            with pytest.raises(LTPFetchError) as exc_info:
                client.get_ltp(exchange="NSE", tradingsymbol="NIFTY", symboltoken="token_test_2")
            assert "Failed to fetch live LTP" in str(exc_info.value)


def test_get_ltp_with_meta_live_and_stale_cache():
    import time
    from angelone_client import _memory_cache, BadSymbolTokenError

    client = AngelOneClient(
        api_key="mock_key",
        client_id="mock_id",
        password="mock_pass",
        totp_secret="JBSWY3DPEHPK3PXP"
    )
    mock_smart_connect = MagicMock()
    mock_smart_connect.generateSession.return_value = {
        "status": True,
        "data": {"jwtToken": "mock_jwt", "feedToken": "mock_feed"}
    }

    # 1. Successful live fetch returns source="live"
    mock_smart_connect.ltpData.return_value = {"status": True, "data": {"ltp": 23500.50}}
    with patch("angelone_client.get_redis_client", return_value=None):
        with patch("angelone_client.SmartConnect", return_value=mock_smart_connect):
            client.login()
            res = client.get_ltp_with_meta("NSE", "NIFTY-TEST", "token_meta_1")
            assert res["price"] == 23500.50
            assert res["source"] == "live"
            assert isinstance(res["fetched_at"], float)

            # Subsequent call within 10s returns source="cache"
            res_cached = client.get_ltp_with_meta("NSE", "NIFTY-TEST", "token_meta_1")
            assert res_cached["price"] == 23500.50
            assert res_cached["source"] == "cache"

    # 2. Stale cache within STALE_MAX_AGE_SECONDS (e.g. 12s old <= 15s) is served when live fetch fails
    cache_key = "ltp:NSE:token_stale_1"
    now = time.time()
    _memory_cache[cache_key] = {"price": 123.45, "time": now - 12.0}

    mock_smart_connect.ltpData.return_value = {"status": False, "message": "Server error"}
    with patch("angelone_client.get_redis_client", return_value=None):
        with patch("angelone_client.SmartConnect", return_value=mock_smart_connect):
            client.login()
            # Stale within 15s succeeds with source="cache"
            meta = client.get_ltp_with_meta("NSE", "NIFTY-STALE", "token_stale_1")
            assert meta["price"] == 123.45
            assert meta["source"] == "cache"

    # 3. Cache older than STALE_MAX_AGE_SECONDS (e.g. 20s old > 15s) raises LTPFetchError
    _memory_cache[cache_key] = {"price": 123.45, "time": now - 20.0}
    with patch("angelone_client.get_redis_client", return_value=None):
        with patch("angelone_client.SmartConnect", return_value=mock_smart_connect):
            client.login()
            with pytest.raises(LTPFetchError) as exc_info:
                client.get_ltp("NSE", "NIFTY-STALE", "token_stale_1")
            assert "Failed to fetch live LTP" in str(exc_info.value)

    # 4. Bad symbol token raises BadSymbolTokenError
    mock_smart_connect.ltpData.return_value = {"status": False, "message": "AB4046: Symbol token not found"}
    with patch("angelone_client.get_redis_client", return_value=None):
        with patch("angelone_client.SmartConnect", return_value=mock_smart_connect):
            client.login()
            with pytest.raises(BadSymbolTokenError):
                client.get_ltp("NSE", "BAD-SYMBOL", "token_bad_999")
