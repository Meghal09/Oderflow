"""Bybit V5 REST client (public + signed)."""
import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx

from config import cfg


class BybitREST:
    def __init__(self):
        self.http = httpx.Client(base_url=cfg.rest_url, timeout=10)

    def _get(self, path, params=None, auth=False):
        params = params or {}
        headers = {}
        if auth:
            ts, rw = str(int(time.time() * 1000)), "5000"
            qs = urlencode(params)
            sig = hmac.new(cfg.api_secret.encode(), (ts + cfg.api_key + rw + qs).encode(),
                           hashlib.sha256).hexdigest()
            headers = {"X-BAPI-API-KEY": cfg.api_key, "X-BAPI-TIMESTAMP": ts,
                       "X-BAPI-RECV-WINDOW": rw, "X-BAPI-SIGN": sig}
        r = self.http.get(path, params=params, headers=headers)
        r.raise_for_status()
        j = r.json()
        if j.get("retCode") != 0:
            raise RuntimeError(f"Bybit {path}: {j.get('retCode')} {j.get('retMsg')}")
        return j["result"]

    def validate(self) -> dict:
        """Validate API credentials. Public data works without keys."""
        if not (cfg.api_key and cfg.api_secret):
            return {"status": "public-only", "msg": "No API keys set - public market data only"}
        try:
            r = self._get("/v5/user/query-api", auth=True)
            perms = r.get("permissions", {})
            risky = [k for k in ("ContractTrade", "Spot", "Wallet", "Options", "Derivatives", "Exchange")
                     if perms.get(k)]
            return {"status": "valid", "readOnly": r.get("readOnly"), "risky_perms": risky,
                    "msg": "API key valid" + ("" if r.get("readOnly") == 1 else " - WARNING: key is not read-only")}
        except Exception as e:  # noqa
            return {"status": "invalid", "msg": f"Credential validation failed: {e}"}

    def instruments(self) -> dict:
        out, cursor = {}, None
        while True:
            p = {"category": "linear", "limit": 1000, "status": "Trading"}
            if cursor:
                p["cursor"] = cursor
            r = self._get("/v5/market/instruments-info", p)
            for i in r["list"]:
                out[i["symbol"]] = {
                    "symbol": i["symbol"], "tick": float(i["priceFilter"]["tickSize"]),
                    "qty_step": float(i["lotSizeFilter"]["qtyStep"]),
                    "min_qty": float(i["lotSizeFilter"]["minOrderQty"]),
                    "base": i["baseCoin"], "quote": i["quoteCoin"], "contract": i.get("contractType"),
                    "max_lev": i["leverageFilter"]["maxLeverage"],
                }
            cursor = r.get("nextPageCursor")
            if not cursor:
                return out

    def klines(self, symbol, interval, limit=300):
        r = self._get("/v5/market/kline", {"category": "linear", "symbol": symbol,
                                           "interval": interval, "limit": limit})
        return [[int(x[0])] + [float(y) for y in x[1:6]] for x in reversed(r["list"])]  # t,o,h,l,c,v

    def recent_trades(self, symbol, limit=1000):
        r = self._get("/v5/market/recent-trade", {"category": "linear", "symbol": symbol, "limit": limit})
        return sorted(({"i": t["execId"], "T": int(t["time"]), "p": float(t["price"]),
                        "v": float(t["size"]), "S": t["side"]} for t in r["list"]), key=lambda x: x["T"])

    def tickers(self, symbol):
        return self._get("/v5/market/tickers", {"category": "linear", "symbol": symbol})["list"][0]

    def open_interest(self, symbol, interval="5min", limit=60):
        r = self._get("/v5/market/open-interest", {"category": "linear", "symbol": symbol,
                                                   "intervalTime": interval, "limit": limit})
        return sorted(((int(x["timestamp"]), float(x["openInterest"])) for x in r["list"]))

    def funding_history(self, symbol, limit=20):
        r = self._get("/v5/market/funding/history", {"category": "linear", "symbol": symbol, "limit": limit})
        return [(int(x["fundingRateTimestamp"]), float(x["fundingRate"])) for x in r["list"]]

    def orderbook(self, symbol, limit=200):
        r = self._get("/v5/market/orderbook", {"category": "linear", "symbol": symbol, "limit": limit})
        return r["b"], r["a"]
