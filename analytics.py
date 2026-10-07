"""Order-flow analytics: footprint, CVD, volume profile, book, smart-money, regime."""
from __future__ import annotations

import numpy as np

from state import rnd


def candle_delta(lv):
    return sum(a - b for b, a in lv.values())


def atr(h, l, c, n=14):
    h, l, c = (np.asarray(x, float) for x in (h, l, c))
    if len(c) < 2:
        return 0.0
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return float(tr[-n:].mean())


# ---------------------------------------------------------------- footprint ------
def imbalances(levels, bucket, ratio=3.0, stack_n=3):
    """Diagonal imbalances. Buy: ask@p >= ratio * bid@(p-1). Sell: bid@p >= ratio * ask@(p+1)."""
    buy, sell = [], []
    for p, (bid, ask) in levels.items():
        lo, hi = levels.get(rnd(p - bucket, bucket)), levels.get(rnd(p + bucket, bucket))
        if lo and ask > 0 and ask >= ratio * max(lo[0], 1e-12):
            buy.append(p)
        if hi and bid > 0 and bid >= ratio * max(hi[1], 1e-12):
            sell.append(p)
    vols = np.array([b + a for b, a in levels.values()]) if levels else np.array([0.0])
    p85 = float(np.percentile(vols, 85))
    agg_buy = [p for p in buy if sum(levels[p]) >= p85]
    agg_sell = [p for p in sell if sum(levels[p]) >= p85]
    return dict(buy=sorted(buy), sell=sorted(sell), agg_buy=agg_buy, agg_sell=agg_sell,
                buy_stacks=_stacks(buy, bucket, stack_n), sell_stacks=_stacks(sell, bucket, stack_n))


def _stacks(prices, bucket, n):
    out, run = [], []
    for p in sorted(prices):
        if run and abs(p - (run[-1] + bucket)) < bucket * 1e-3:
            run.append(p)
        else:
            if len(run) >= n:
                out.append((run[0], run[-1]))
            run = [p]
    if len(run) >= n:
        out.append((run[0], run[-1]))
    return out


# --------------------------------------------------------------------- CVD ------
def cvd_series(v, roll=30):
    d = np.array([candle_delta(v["fp"].get(t, {})) for t in v["t"]], float)
    sess, acc, cur = np.zeros(len(d)), 0.0, None
    for i, t in enumerate(v["t"]):
        day = t // 86_400_000
        if day != cur:
            acc, cur = 0.0, day
        acc += d[i]
        sess[i] = acc
    rolling = np.convolve(d, np.ones(roll))[:len(d)]
    return d, sess, rolling


def pivots(x, k=2):
    hi, lo = [], []
    for i in range(k, len(x) - k):
        w = x[i - k:i + k + 1]
        if x[i] == w.max():
            hi.append(i)
        if x[i] == w.min():
            lo.append(i)
    return hi, lo


def divergences(v, cvd, k=2, lookback=60, recent=12):
    h, l = np.asarray(v["h"]), np.asarray(v["l"])
    n = len(h)
    s = max(0, n - lookback)
    out = []
    if np.ptp(cvd[s:]) == 0:
        return out
    hi, _ = pivots(h[s:], k)
    _, lo = pivots(l[s:], k)
    if len(hi) >= 2 and s + hi[-1] >= n - recent:
        a, b = s + hi[-2], s + hi[-1]
        if h[b] > h[a] and cvd[b] < cvd[a]:
            out.append(dict(kind="bearish", i=b, price=h[b]))
    if len(lo) >= 2 and s + lo[-1] >= n - recent:
        a, b = s + lo[-2], s + lo[-1]
        if l[b] < l[a] and cvd[b] > cvd[a]:
            out.append(dict(kind="bullish", i=b, price=l[b]))
    return out


# ----------------------------------------------------------- volume profile -----
def volume_profile(v, last_n=None, va=0.70):
    agg = {}
    for t in (v["t"][-last_n:] if last_n else v["t"]):
        for p, (b, a) in v["fp"].get(t, {}).items():
            agg[p] = agg.get(p, 0.0) + b + a
    if len(agg) < 3:
        return None
    prices = sorted(agg)
    vols = np.array([agg[p] for p in prices])
    poc = int(vols.argmax())
    lo = hi = poc
    acc, target = vols[poc], va * vols.sum()
    while acc < target and (lo > 0 or hi < len(vols) - 1):
        up = vols[hi + 1] if hi < len(vols) - 1 else -1
        dn = vols[lo - 1] if lo > 0 else -1
        if up >= dn:
            hi += 1
            acc += vols[hi]
        else:
            lo -= 1
            acc += vols[lo]
    m, sd = vols.mean(), vols.std()
    hvn = [prices[i] for i in range(1, len(vols) - 1)
           if vols[i] >= vols[i - 1] and vols[i] >= vols[i + 1] and vols[i] > m + 0.5 * sd]
    lvn = [prices[i] for i in range(max(lo, 1), min(hi, len(vols) - 2) + 1)
           if vols[i] <= vols[i - 1] and vols[i] <= vols[i + 1] and vols[i] < 0.5 * m]
    return dict(prices=prices, vols=vols.tolist(), poc=prices[poc], vah=prices[hi], val=prices[lo],
                hvn=hvn, lvn=lvn)


# ---------------------------------------------------------------- order book ----
def book_analysis(bids, asks, prev, trades_5s, mult=4.0, band=0.01):
    if not bids or not asks:
        return None
    mid = (max(bids) + min(asks)) / 2
    nb = {p: s for p, s in bids.items() if p >= mid * (1 - band)}
    na = {p: s for p, s in asks.items() if p <= mid * (1 + band)}
    sizes = np.array(list(nb.values()) + list(na.values()))
    if len(sizes) < 10:
        return None
    med = float(np.median(sizes))
    walls = {(sd, p): s for sd, dct in (("bid", nb), ("ask", na)) for p, s in dct.items() if s >= mult * med}
    traded = {}
    for _, p, sz, _s in trades_5s:
        traded[p] = traded.get(p, 0) + sz
    shifts = [("new wall", k[0], k[1], s) for k, s in walls.items() if k not in prev]
    for k, s in prev.items():
        if walls.get(k, 0) < 0.5 * s:
            shifts.append(("filled wall" if traded.get(k[1], 0) >= 0.3 * s else "pulled wall", k[0], k[1], s))
    return dict(mid=mid, walls=walls, shifts=shifts, median=med,
                ratio=sum(nb.values()) / max(sum(na.values()), 1e-9))


def heat_row(bids, asks, mid, n=40, span_bps=50):
    row, step = np.zeros(n), span_bps * 2 / n
    for dct in (bids, asks):
        for p, s in dct.items():
            b = (p - mid) / mid * 1e4
            if -span_bps <= b < span_bps:
                row[int((b + span_bps) / step)] += s
    return row


def absorption(trades, now_ms, atr_, win=30_000):
    rec = [t for t in trades if t[0] >= now_ms - win]
    if len(rec) < 20:
        return None
    vol = sum(t[2] for t in rec)
    base = sum(t[2] for t in trades) / max(1, (now_ms - trades[0][0]) / win)
    delta = sum(t[2] if t[3] == "Buy" else -t[2] for t in rec)
    px = [t[1] for t in rec]
    if vol > 2 * base and abs(delta) > 0.35 * vol and (max(px) - min(px)) < 0.35 * atr_:
        return dict(dir=1 if delta < 0 else -1, lo=min(px), hi=max(px), delta=delta, vol=vol)
    return None


def icebergs(trades, bids, asks, now_ms, win=60_000, ratio=3.0, min_trades=8):
    g = {}
    for ts, p, sz, side in trades:
        if ts >= now_ms - win:
            e = g.setdefault((p, side), [0.0, 0])
            e[0] += sz
            e[1] += 1
    out = []
    for (p, side), (vol, n) in g.items():
        if n < min_trades:
            continue
        if side == "Buy" and p in asks and vol > ratio * asks[p] and min(asks) >= p:
            out.append(dict(dir=-1, price=p, vol=vol, shown=asks[p]))   # hidden seller refilling the ask
        if side == "Sell" and p in bids and vol > ratio * bids[p] and max(bids) <= p:
            out.append(dict(dir=1, price=p, vol=vol, shown=bids[p]))    # hidden buyer refilling the bid
    return out


# ---------------------------------------------------------------- smart money ---
def sweeps(v, d, lookback=20, volx=1.3):
    n = len(v["t"])
    i = n - 2
    if i < lookback + 1:
        return []
    h, l, o, c, vol = (np.asarray(v[k], float) for k in ("h", "l", "o", "c", "v"))
    rng = max(h[i] - l[i], 1e-12)
    avg = vol[i - lookback:i].mean()
    out = []
    if h[i] > h[i - lookback:i].max() and c[i] < h[i - lookback:i].max() and vol[i] >= volx * avg:
        w = (h[i] - max(o[i], c[i])) / rng
        if w >= 0.4:
            out.append(dict(dir=-1, level=float(h[i - lookback:i].max()), extreme=float(h[i]), wick=w,
                            hunt=w >= 0.6 and vol[i] >= 1.8 * avg, i=i))
    if l[i] < l[i - lookback:i].min() and c[i] > l[i - lookback:i].min() and vol[i] >= volx * avg:
        w = (min(o[i], c[i]) - l[i]) / rng
        if w >= 0.4:
            out.append(dict(dir=1, level=float(l[i - lookback:i].min()), extreme=float(l[i]), wick=w,
                            hunt=w >= 0.6 and vol[i] >= 1.8 * avg, i=i))
    return out


def exhaustion(v, d, n=10):
    k = len(v["t"]) - 2
    if k < n + 3:
        return []
    h, l = np.asarray(v["h"]), np.asarray(v["l"])
    out = []
    if h[k] >= h[k - n:k].max() and d[k] < 0 < d[k - 3:k].mean():
        out.append(dict(dir=-1, price=float(h[k]), i=k))   # buying exhaustion at highs
    if l[k] <= l[k - n:k].min() and d[k] > 0 > d[k - 3:k].mean():
        out.append(dict(dir=1, price=float(l[k]), i=k))    # selling exhaustion at lows
    return out


def trapped(v, d, lookback=15):
    n = len(v["t"])
    k = n - 2
    if k < lookback + 5:
        return []
    h, l, c = (np.asarray(v[x], float) for x in ("h", "l", "c"))
    out = []
    for j in range(k - 3, k):
        up, dn = h[j - lookback:j].max(), l[j - lookback:j].min()
        if c[j] > up and d[j] > 0 and c[k] < up and d[k] < 0:
            out.append(dict(dir=-1, level=float(up), extreme=float(h[j:k + 1].max()), i=k))   # trapped longs
        if c[j] < dn and d[j] < 0 and c[k] > dn and d[k] > 0:
            out.append(dict(dir=1, level=float(dn), extreme=float(l[j:k + 1].min()), i=k))    # trapped shorts
    return out[:1]


def oi_divergence(oi, now_ms, win=600_000, p_min=0.15, oi_min=0.3):
    pts = [x for x in oi if x[0] >= now_ms - win]
    if len(pts) < 3 or pts[-1][0] - pts[0][0] < win * 0.5:
        return None
    pc = (pts[-1][2] / pts[0][2] - 1) * 100
    oc = (pts[-1][1] / pts[0][1] - 1) * 100
    if pc > p_min and oc < -oi_min:
        return dict(dir=-1, price_chg=pc, oi_chg=oc)
    if pc < -p_min and oc > oi_min:
        return dict(dir=1, price_chg=pc, oi_chg=oc)
    return None


# -------------------------------------------------------------------- regime ----
def regime(v, tk, trend_chg=5.0, vol_ratio=1.5):
    c = np.asarray(v["c"], float)
    a14 = atr(v["h"], v["l"], c, 14)
    a100 = atr(v["h"], v["l"], c, 100) or a14
    ratio = a14 / a100 if a100 else 1.0
    chg = tk.get("price24hPcnt", 0) * 100
    hi, lo = tk.get("highPrice24h"), tk.get("lowPrice24h")
    pos = (c[-1] - lo) / (hi - lo) if hi and lo and hi > lo else 0.5
    w = c[-50:]
    er = abs(w[-1] - w[0]) / max(np.abs(np.diff(w)).sum(), 1e-9) if len(w) > 2 else 0.0
    if ratio >= vol_ratio:
        name, conf = "volatile", min(1, 0.5 + (ratio - vol_ratio))
    elif (abs(chg) >= trend_chg and (pos > 0.65 or pos < 0.35)) or er >= 0.35:
        name, conf = "trending", min(1, 0.5 + max(er, abs(chg) / 20))
    else:
        name, conf = "ranging", min(1, 0.5 + (0.35 - er))
    return dict(name=name, conf=round(float(conf), 2), chg24=chg, pos=float(pos), atr_ratio=float(ratio),
                er=float(er), atr=a14)
