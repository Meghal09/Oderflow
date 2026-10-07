"""Async engine: Bybit WebSocket feeds + REST seeding + 1s analytics loop (own thread)."""
import asyncio
import json
import logging
import threading

import websockets

import signals as S
from bybit_client import BybitREST
from config import cfg
from state import MarketState

log = logging.getLogger("engine")


class Engine:
    def __init__(self):
        self.rest = BybitREST()
        self.state: MarketState | None = None
        self.instruments, self.auth = {}, {"status": "unchecked", "msg": ""}
        self.loop, self.ready = None, threading.Event()
        self.desired, self.subscribed, self._ws = set(), set(), None
        self.ws_status = "connecting"

    def start(self):
        threading.Thread(target=lambda: asyncio.run(self._main()), daemon=True, name="engine").start()
        self.ready.wait(60)

    def switch(self, symbol, tf):
        """Blocking symbol / timeframe switch (called from Dash callbacks)."""
        if self.state and (self.state.symbol, str(self.state.tf)) == (symbol, str(tf)):
            return
        asyncio.run_coroutine_threadsafe(self._switch(symbol, str(tf)), self.loop).result(30)

    async def _main(self):
        self.loop = asyncio.get_running_loop()
        self.auth = await asyncio.to_thread(self.rest.validate)
        self.instruments = await asyncio.to_thread(self.rest.instruments)
        await self._switch(cfg.symbol, cfg.tf)
        self.ready.set()
        await asyncio.gather(self._ws_loop(), self._sync_loop(), self._analytics_loop())

    async def _switch(self, symbol, tf):
        if symbol not in self.instruments:
            raise ValueError(f"Unknown linear symbol {symbol}")
        r = self.rest
        kl, tr, tk, oi = await asyncio.gather(
            asyncio.to_thread(r.klines, symbol, tf, 300), asyncio.to_thread(r.recent_trades, symbol, 1000),
            asyncio.to_thread(r.tickers, symbol), asyncio.to_thread(r.open_interest, symbol))
        st = MarketState(symbol, tf, self.instruments[symbol]["tick"])
        st.seed(kl, tr, tk, oi, cfg.bucket_bps)
        self.state = st
        self.desired = {f"publicTrade.{symbol}", f"orderbook.200.{symbol}", f"tickers.{symbol}",
                        f"kline.{tf}.{symbol}"}

    # ---- websocket ---------------------------------------------------------------
    async def _ws_loop(self):
        backoff = 1
        while True:
            try:
                async with websockets.connect(cfg.ws_url, ping_interval=None, max_size=2 ** 23) as ws:
                    self._ws, self.subscribed, backoff = ws, set(), 1
                    self.ws_status = "live"
                    hb = asyncio.create_task(self._heartbeat(ws))
                    try:
                        async for raw in ws:
                            self._dispatch(json.loads(raw))
                    finally:
                        hb.cancel()
            except Exception as e:  # noqa
                log.warning("ws error: %s", e)
            self._ws, self.ws_status = None, "reconnecting"
            await asyncio.sleep(backoff)
            backoff = min(30, backoff * 2)

    async def _heartbeat(self, ws):
        while True:
            await asyncio.sleep(20)
            await ws.send(json.dumps({"op": "ping"}))

    async def _sync_loop(self):
        while True:
            await asyncio.sleep(0.3)
            ws = self._ws
            if not ws:
                continue
            add, rem = self.desired - self.subscribed, self.subscribed - self.desired
            try:
                if rem:
                    await ws.send(json.dumps({"op": "unsubscribe", "args": sorted(rem)}))
                if add:
                    await ws.send(json.dumps({"op": "subscribe", "args": sorted(add)}))
                self.subscribed = set(self.desired)
            except Exception as e:  # noqa
                log.warning("sub error: %s", e)

    def _dispatch(self, m):
        topic, st = m.get("topic", ""), self.state
        if not topic or st is None or topic.split(".")[-1] != st.symbol:
            return
        d = m["data"]
        if topic.startswith("publicTrade."):
            for t in d:
                st.add_trade(int(t["T"]), float(t["p"]), float(t["v"]), t["S"], t["i"])
        elif topic.startswith("orderbook."):
            st.apply_book(m["type"], d)
        elif topic.startswith("tickers."):
            st.apply_ticker(d)
        elif topic.startswith("kline."):
            for k in d:
                st.upsert_kline({"start": k["start"], "open": k["open"], "high": k["high"],
                                 "low": k["low"], "close": k["close"], "volume": k["volume"]})

    async def _analytics_loop(self):
        while True:
            await asyncio.sleep(1)
            try:
                if self.state:
                    S.compute(self.state)
            except Exception:  # noqa
                log.exception("analytics failed")
