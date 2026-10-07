"""AlgoDesk agent routing + signal / risk engine (REGIME -> FLOW/LIQ/CONTRA/RANGE/OIDIV/FUND)."""
from __future__ import annotations

import time

import numpy as np

import analytics as A
from config import cfg

# From the AlgoDesk 17-agent framework: SL %, size % of portfolio, regimes in which agent is active.
AGENTS = {
    "FLOW":   dict(sl=1.5, size=11, regimes={"trending"}),
    "LIQ":    dict(sl=1.5, size=6,  regimes={"volatile"}),
    "CONTRA": dict(sl=2.0, size=8,  regimes={"volatile"}),
    "RANGE":  dict(sl=1.0, size=10, regimes={"ranging"}),
    "MEAN":   dict(sl=3.0, size=12, regimes={"ranging"}),
    "OIDIV":  dict(sl=1.0, size=6,  regimes={"trending", "ranging", "volatile"}),   # always-active
    "FUND":   dict(sl=0.5, size=5,  regimes={"trending", "ranging", "volatile"}),   # always-active
    "SENT":   dict(sl=1.0, size=7,  regimes={"trending", "ranging", "volatile"}),
}
TGT_MULT = {"trending": 3.0, "ranging": 1.5, "volatile": 2.0}   # volatility-adjusted target (xATR)
BASE_CONF = dict(div=.60, imb=.55, sweep=.65, absorb=.60, exhaust=.55, trap=.60, iceberg=.50,
                 oidiv=.50, funding=.50, setup=.70)
REVERSAL = {"div", "sweep", "absorb", "exhaust", "trap"}


def make_setup(direction, zone, stop_ref, atr_, reg, agent):
    lo, hi = sorted(zone)
    entry = (lo + hi) / 2
    dist = max(abs(entry - (stop_ref - direction * 0.25 * atr_)), 0.6 * atr_)
    stop = entry - direction * dist
    m = TGT_MULT[reg] * atr_
    tps = [entry + direction * m * f for f in (0.6, 1.0, 1.5)]
    a = AGENTS[agent]
    return dict(entry_lo=lo, entry_hi=hi, entry=entry, stop=stop, targets=tps,
                rr=round(m / dist, 2), risk_pct=dist / entry * 100, size_pct=a["size"],
                sl_cap_exceeded=dist > a["sl"] / 100 * entry)


def _fire(st, now, kind, label, direction, agent, zone, stop_ref, reg, atr_, note, cd_ms=60_000, key_extra=""):
    key = (kind, direction, key_extra)
    if now - st.cool.get(key, 0) < cd_ms:
        return None
    st.cool[key] = now
    ok = reg["name"] in AGENTS[agent]["regimes"]
    s = make_setup(direction, zone, stop_ref, atr_, reg["name"], agent)
    s.update(ts=now, kind=kind, label=label, dir=direction, agent=agent, regime=reg["name"], regime_ok=ok,
             note=note, conf=0.0)
    st.events.append((now, kind, direction))
    return s


def compute(st):
    now = int(time.time() * 1000)
    v = st.view(150, now)
    if len(v["t"]) < 25:
        return
    tk, bucket = v["ticker"], v["bucket"]
    d, sess, roll = A.cvd_series(v, cfg.roll_candles)
    reg = A.regime(v, tk, cfg.trend_chg, cfg.vol_ratio)
    atr_ = reg["atr"] or bucket * 5
    last = v["c"][-1]
    tf = v["tf_ms"]

    # --- footprint imbalances (visible candles)
    vis = v["t"][-cfg.fp_candles:]
    imb = {t: A.imbalances(v["fp"][t], bucket, cfg.imb_ratio, cfg.stack_n) for t in vis if t in v["fp"]}
    prof_s, prof_w = A.volume_profile(v), A.volume_profile(v, cfg.fp_candles)

    # --- book
    tr5 = [x for x in v["trades"] if x[0] >= now - 5000]
    book = A.book_analysis(v["bids"], v["asks"], st.prev_walls, tr5, cfg.wall_mult)
    if book:
        st.prev_walls = book["walls"]
        if now - (st.book_hist[-1][0] if st.book_hist else 0) >= 1000:
            st.book_hist.append((now, book["mid"], A.heat_row(v["bids"], v["asks"], book["mid"])))

    sigs = []
    f = lambda *a, **k: sigs.append(x) if (x := _fire(st, now, *a, reg=reg, atr_=atr_, **k)) else None  # noqa

    # --- CVD divergence
    for dv in A.divergences(v, sess):
        dr = 1 if dv["kind"] == "bullish" else -1
        f("div", f"{dv['kind'].title()} delta divergence", dr, "FLOW", (last - atr_ * .15, last + atr_ * .15),
          dv["price"], note="Price extreme not confirmed by session CVD", cd_ms=tf, key_extra=v["t"][dv["i"]])
    # --- imbalance clusters (forming + last closed candle)
    for t, im in list(imb.items())[-2:]:
        for lo, hi in im["buy_stacks"]:
            f("imb", "Buy imbalance cluster", 1, "FLOW", (lo, hi), lo, note=f"{cfg.stack_n}+ stacked buy imbalances",
              cd_ms=tf, key_extra=t)
        for lo, hi in im["sell_stacks"]:
            f("imb", "Sell imbalance cluster", -1, "FLOW", (lo, hi), hi, note=f"{cfg.stack_n}+ stacked sell imbalances",
              cd_ms=tf, key_extra=t)
    # --- smart money
    for s in A.sweeps(v, d):
        lbl = "Stop hunt" if s["hunt"] else "Liquidity sweep"
        f("sweep", f"{lbl} ({'lows' if s['dir'] > 0 else 'highs'})", s["dir"], "LIQ",
          (s["level"], s["level"] + s["dir"] * 0.2 * atr_), s["extreme"], note=f"Wick {s['wick']:.0%} of range, closed back inside",
          cd_ms=tf, key_extra=v["t"][s["i"]])
    for s in A.exhaustion(v, d):
        f("exhaust", "Buying exhaustion" if s["dir"] < 0 else "Selling exhaustion", s["dir"], "CONTRA",
          (last - atr_ * .1, last + atr_ * .1), s["price"], note="New extreme, delta flipped against it", cd_ms=tf,
          key_extra=v["t"][s["i"]])
    for s in A.trapped(v, d):
        f("trap", "Trapped longs" if s["dir"] < 0 else "Trapped shorts", s["dir"], "LIQ",
          (s["level"] - atr_ * .1, s["level"] + atr_ * .1), s["extreme"], note="Failed breakout, delta reversed", cd_ms=tf,
          key_extra=v["t"][s["i"]])
    ab = A.absorption(v["trades"], now, atr_)
    if ab:
        f("absorb", "Sell absorption" if ab["dir"] > 0 else "Buy absorption", ab["dir"], "RANGE", (ab["lo"], ab["hi"]),
          ab["lo"] if ab["dir"] > 0 else ab["hi"], note=f"Heavy one-sided aggression absorbed, delta {ab['delta']:.2f}",
          cd_ms=60_000)
    ice = A.icebergs(v["trades"], v["bids"], v["asks"], now)
    for ic in ice[:2]:
        f("iceberg", "Iceberg (hidden buyer)" if ic["dir"] > 0 else "Iceberg (hidden seller)", ic["dir"], "FLOW",
          (ic["price"], ic["price"] + ic["dir"] * 0.1 * atr_), ic["price"],
          note=f"Executed {ic['vol']:.2f} vs {ic['shown']:.2f} displayed", cd_ms=90_000, key_extra=str(ic["price"]))
    od = A.oi_divergence(v["oi"], now)
    if od:
        f("oidiv", "OI divergence", od["dir"], "OIDIV", (last - atr_ * .1, last + atr_ * .1),
          last - od["dir"] * atr_, note=f"Price {od['price_chg']:+.2f}% vs OI {od['oi_chg']:+.2f}% (10m)", cd_ms=300_000)
    fr = tk.get("fundingRate")
    if fr is not None and abs(fr) >= cfg.funding_thr:
        dr = -1 if fr > 0 else 1
        f("funding", "Funding extreme", dr, "FUND", (last - atr_ * .1, last + atr_ * .1), last - dr * atr_,
          note=f"Funding {fr * 100:.3f}%", cd_ms=1_800_000)

    # --- composite setups: confluence of events in last 5 candles
    win = now - 5 * tf
    ev = [(k, dr) for ts, k, dr in st.events if ts >= win]
    for dr in (1, -1):
        rk = {k for k, x in ev if x == dr and k in REVERSAL}
        if len(rk) >= 2:
            s = _fire(st, now, "setup", f"Potential reversal setup ({'LONG' if dr > 0 else 'SHORT'})", dr, "LIQ",
                      (last - atr_ * .2, last + atr_ * .2), last - dr * atr_, reg, atr_,
                      note="Confluence: " + ", ".join(sorted(rk)), cd_ms=5 * tf, key_extra="rev")
            if s:
                sigs.append(s)
        has_stack = any(k == "imb" and x == dr for k, x in ev)
        slope = np.sign(roll[-1] - roll[-5]) if len(roll) > 5 else 0
        poc = prof_s["poc"] if prof_s else last
        if has_stack and slope == dr and (last - poc) * dr > 0:
            s = _fire(st, now, "setup", f"Potential continuation setup ({'LONG' if dr > 0 else 'SHORT'})", dr, "FLOW",
                      (last - atr_ * .2, last + atr_ * .2), last - dr * atr_, reg, atr_,
                      note="Imbalance stack + rolling CVD slope + price vs POC aligned", cd_ms=5 * tf, key_extra="cont")
            if s:
                sigs.append(s)

    for s in sigs:  # confidence = base + regime + confluence
        confirms = sum(1 for k, x in ev if x == s["dir"] and k != s["kind"])
        s["conf"] = round(min(0.95, BASE_CONF[s["kind"]] + (0.1 if s["regime_ok"] else -0.15) + 0.08 * confirms), 2)
        st.alerts.appendleft(s)

    st.snapshot = dict(v=v, d=d, sess=sess, roll=roll, reg=reg, atr=atr_, imb=imb, prof_s=prof_s, prof_w=prof_w,
                       book=book, div=A.divergences(v, sess), ts=now, last=last, iceberg=ice)
