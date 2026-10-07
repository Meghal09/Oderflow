"""Thread-safe per-symbol market state: candles, footprint, tape, book."""
import math
import threading
from collections import deque


def rnd(x, b):
    return round(round(x / b) * b, 10)


def nice_bucket(price, tick, bps):
    x = max(price * bps / 1e4, tick)
    e = math.floor(math.log10(x))
    f = x / 10 ** e
    f = 1 if f < 1.5 else 2 if f < 3.5 else 5 if f < 7.5 else 10
    return max(tick, rnd(f * 10 ** e, tick))


class MarketState:
    def __init__(self, symbol, tf, tick):
        self.lock = threading.RLock()
        self.symbol, self.tf, self.tick = symbol, int(tf), tick
        self.tf_ms = self.tf * 60_000
        self.bucket = tick
        self.candles = {}                 # start_ms -> [o,h,l,c,v]
        self.fp = {}                      # start_ms -> {level: [bid_vol, ask_vol]}
        self.trades = deque(maxlen=40000)  # (ts, price, size, side)
        self._seen = deque(maxlen=5000)
        self._seen_set = set()
        self.bids, self.asks = {}, {}
        self.book_hist = deque(maxlen=300)  # (ts, mid, row)
        self.ticker = {}
        self.oi_hist = deque(maxlen=400)    # (ts, oi, price)
        self.alerts = deque(maxlen=200)
        self.events = deque(maxlen=400)     # (ts, kind, dir)
        self.cool = {}
        self.prev_walls = {}
        self.prev_walls_ts = 0
        self.snapshot = {}

    # ---- seeding ----------------------------------------------------------------
    def seed(self, klines, trades, ticker, oi, bucket_bps):
        with self.lock:
            for k in klines:
                self.candles[k[0]] = k[1:6]
            if ticker:
                self.apply_ticker(ticker)
            last = klines[-1][4] if klines else float(ticker.get("lastPrice", 0))
            self.bucket = nice_bucket(last, self.tick, bucket_bps)
            for t in trades:
                self.add_trade(t["T"], t["p"], t["v"], t["S"], t["i"])
            px = last or 1
            for ts, v in oi:
                self.oi_hist.append((ts, v, px))

    # ---- stream handlers --------------------------------------------------------
    def add_trade(self, ts, price, size, side, exec_id=None):
        with self.lock:
            if exec_id:
                if exec_id in self._seen_set:
                    return
                if len(self._seen) == self._seen.maxlen:
                    self._seen_set.discard(self._seen[0])
                self._seen.append(exec_id)
                self._seen_set.add(exec_id)
            self.trades.append((ts, price, size, side))
            start = ts // self.tf_ms * self.tf_ms
            lv = self.fp.setdefault(start, {}).setdefault(rnd(price, self.bucket), [0.0, 0.0])
            lv[1 if side == "Buy" else 0] += size     # Buy taker lifts ask, Sell taker hits bid
            c = self.candles.get(start)
            if c is None:
                self.candles[start] = [price, price, price, price, size]
            if len(self.fp) > 700:
                for k in sorted(self.fp)[:100]:
                    self.fp.pop(k, None)

    def upsert_kline(self, k):
        with self.lock:
            self.candles[int(k["start"])] = [float(k["open"]), float(k["high"]), float(k["low"]),
                                             float(k["close"]), float(k["volume"])]
            if len(self.candles) > 900:
                for t in sorted(self.candles)[:100]:
                    self.candles.pop(t, None)

    def apply_book(self, typ, d):
        with self.lock:
            if typ == "snapshot":
                self.bids = {float(p): float(s) for p, s in d["b"]}
                self.asks = {float(p): float(s) for p, s in d["a"]}
                return
            for side, dct in (("b", self.bids), ("a", self.asks)):
                for p, s in d.get(side, []):
                    p, s = float(p), float(s)
                    if s == 0:
                        dct.pop(p, None)
                    else:
                        dct[p] = s

    def apply_ticker(self, d):
        with self.lock:
            for k in ("lastPrice", "markPrice", "fundingRate", "openInterest", "openInterestValue",
                      "price24hPcnt", "highPrice24h", "lowPrice24h", "volume24h", "turnover24h",
                      "nextFundingTime"):
                if d.get(k) not in (None, ""):
                    self.ticker[k] = float(d[k])
            if "openInterest" in self.ticker and "lastPrice" in self.ticker:
                now = int(__import__("time").time() * 1000)
                if not self.oi_hist or now - self.oi_hist[-1][0] >= 5000:
                    self.oi_hist.append((now, self.ticker["openInterest"], self.ticker["lastPrice"]))

    # ---- read side --------------------------------------------------------------
    def view(self, n=150, now_ms=None):
        with self.lock:
            ts = sorted(self.candles)[-n:]
            now_ms = now_ms or (ts[-1] + self.tf_ms if ts else 0)
            return dict(
                t=ts, o=[self.candles[x][0] for x in ts], h=[self.candles[x][1] for x in ts],
                l=[self.candles[x][2] for x in ts], c=[self.candles[x][3] for x in ts],
                v=[self.candles[x][4] for x in ts],
                fp={x: {p: tuple(q) for p, q in self.fp[x].items()} for x in ts if x in self.fp},
                bucket=self.bucket, tick=self.tick, tf_ms=self.tf_ms,
                trades=[x for x in self.trades if x[0] >= now_ms - 600_000],
                bids=dict(self.bids), asks=dict(self.asks), ticker=dict(self.ticker),
                oi=list(self.oi_hist),
            )
