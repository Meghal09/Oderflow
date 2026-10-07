"""Static preview (matplotlib) of the dashboard layout using the smoke-test data."""
import os, sys, runpy
import numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
g = runpy.run_path(os.path.join(os.path.dirname(__file__), "smoke_test.py"))
s, st = g["s"], g["st"]
from config import cfg
from state import rnd
v, b = s["v"], s["v"]["bucket"]
BG, G, R, B, Y = "#0e1117", "#26a69a", "#ef5350", "#4fc3f7", "#ffd54f"
plt.rcParams.update({"figure.facecolor": BG, "axes.facecolor": BG, "text.color": "#ddd", "axes.edgecolor": "#444",
                     "xtick.color": "#aaa", "ytick.color": "#aaa", "axes.labelcolor": "#aaa", "font.size": 8})
fig = plt.figure(figsize=(18, 10.5))
gs = fig.add_gridspec(3, 3, width_ratios=[5, 1, 1.9], height_ratios=[3.2, 4.4, 2.4], hspace=.18, wspace=.08)
n = 70; t = np.arange(n); o, h, l, c = (np.array(v[k][-n:]) for k in "ohlc")
a1 = fig.add_subplot(gs[0, 0])
for i in range(n):
    col = G if c[i] >= o[i] else R
    a1.plot([i, i], [l[i], h[i]], color=col, lw=.8); a1.add_patch(Rectangle((i-.35, min(o[i], c[i])), .7, max(abs(c[i]-o[i]), .5), color=col))
p = s["prof_s"]
for y, nm, col in ((p["poc"], "POC", Y), (p["vah"], "VAH", B), (p["val"], "VAL", B)):
    a1.axhline(y, ls=":", color=col, lw=1); a1.text(0, y, nm, color=col, va="bottom")
a1.set_title("BTCUSDT 1m  |  REGIME %s  ATR %.1f  (synthetic data)" % (s["reg"]["name"].upper(), s["atr"]), loc="left", fontsize=10)
a1p = fig.add_subplot(gs[0, 1], sharey=a1); a1p.barh(p["prices"], p["vols"], height=b*.9, color=[Y if q == p["poc"] else "#607d8b" for q in p["prices"]])
a1p.set_title("Volume profile", fontsize=9); plt.setp(a1p.get_yticklabels(), visible=False)
# footprint
vis = v["t"][-cfg.fp_candles:]; allp = [q for x in vis for q in v["fp"].get(x, {})]
lo, hi = min(allp), max(allp); lv = [rnd(lo+i*b, b) for i in range(int(round((hi-lo)/b))+1)]
a2 = fig.add_subplot(gs[1, 0]); zm = 1e-9
for j, x in enumerate(vis):
    for q, (bd, ak) in v["fp"].get(x, {}).items(): zm = max(zm, abs(ak-bd))
for j, x in enumerate(vis):
    im = s["imb"].get(x, {"buy": [], "sell": [], "agg_buy": [], "agg_sell": []})
    for q, (bd, ak) in v["fp"].get(x, {}).items():
        d = (ak-bd)/zm; col = plt.cm.RdYlGn((d+1)/2)
        a2.add_patch(Rectangle((j-.45, q-b*.48), .9, b*.96, color=col, alpha=.85))
        a2.text(j, q, f"{bd:.2g}×{ak:.2g}", ha="center", va="center", fontsize=6, color="black")
        if q in im["buy"]: a2.add_patch(Rectangle((j-.45, q-b*.48), .9, b*.96, fill=False, ec="lime", lw=1.6))
        if q in im["sell"]: a2.add_patch(Rectangle((j-.45, q-b*.48), .9, b*.96, fill=False, ec="red", lw=1.6))
        if q in im["agg_buy"]: a2.plot(j+.38, q, "*", color="#00e5ff", ms=7)
        if q in im["agg_sell"]: a2.plot(j+.38, q, "*", color="#ff9100", ms=7)
a2.set_xlim(-.6, len(vis)-.4); a2.set_ylim(lo-b, hi+b)
a2.set_xticks(range(len(vis))); a2.set_xticklabels([__import__("datetime").datetime.utcfromtimestamp(x/1000).strftime("%H:%M") for x in vis])
a2.set_title("Footprint  (bid×ask, colour = delta, green/red box = imbalance, ★ cyan/orange = aggressive buyer/seller)", loc="left", fontsize=9)
pw = s["prof_w"]; a2p = fig.add_subplot(gs[1, 1], sharey=a2)
a2p.barh(pw["prices"], pw["vols"], height=b*.9, color=[Y if q == pw["poc"] else "#607d8b" for q in pw["prices"]]); plt.setp(a2p.get_yticklabels(), visible=False)
a2p.set_title("Profile (footprint window)", fontsize=9)
# CVD
a3 = fig.add_subplot(gs[2, 0]); a3.plot(t, s["sess"][-n:], color=B, label="Session CVD"); a3.plot(t, s["roll"][-n:], color=Y, label="Rolling CVD")
a3.bar(t, s["d"][-n:], color=[G if x >= 0 else R for x in s["d"][-n:]], alpha=.35, label="Δ/candle"); a3.legend(loc="upper left", fontsize=7, frameon=False)
# side
bk = s["book"]; mid = bk["mid"]
bids = sorted(((p_, q) for p_, q in v["bids"].items() if p_ >= mid*.995), reverse=True); asks = sorted((p_, q) for p_, q in v["asks"].items() if p_ <= mid*1.005)
a4 = fig.add_subplot(gs[0, 2]); a4.fill_betweenx([p_ for p_, _ in bids], 0, np.cumsum([q for _, q in bids]), step="post", color=G, alpha=.6)
a4.fill_betweenx([p_ for p_, _ in asks], 0, np.cumsum([q for _, q in asks]), step="post", color=R, alpha=.6)
for (sd, p_), q in bk["walls"].items(): a4.axhline(p_, ls=":", color=G if sd == "bid" else R, lw=1); a4.text(0, p_, f" wall {q:.3g}", fontsize=6)
a4.set_title("Live depth + liquidity walls", fontsize=9)
a5 = fig.add_subplot(gs[1, 2]); hh = list(st.book_hist)
if len(hh) > 2: a5.imshow(np.log1p(np.array([r for _, _, r in hh]).T), aspect="auto", origin="lower", cmap="inferno", extent=[0, len(hh), -50, 50])
a5.set_title("Depth heatmap (bps from mid)", fontsize=9)
a6 = fig.add_subplot(gs[2, 2]); a6.axis("off")
al = list(st.alerts)[:1]; txt = "ALERTS / RISK\n\n"
for a in al:
    txt += f"{'LONG' if a['dir']>0 else 'SHORT'}  {a['label']}\nAgent {a['agent']}  conf {a['conf']:.0%}\nEntry {a['entry_lo']:.1f}–{a['entry_hi']:.1f}\nStop {a['stop']:.1f} ({a['risk_pct']:.2f}%)\nTargets {' / '.join(f'{x:.1f}' for x in a['targets'])}\nR/R 1:{a['rr']}   size {a['size_pct']}%"
a6.text(0, 1, txt, va="top", family="monospace", fontsize=8, color=G)
fig.savefig("/mnt/user-data/outputs/dashboard_preview.png", dpi=110, bbox_inches="tight")
print("saved")
