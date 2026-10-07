"""Offline smoke test: synthetic tape -> analytics -> figures (no network)."""
import os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import signals as S
from state import MarketState
from dashboard import main_fig, depth_fig, heat_fig, alert_cards, risk_card

random.seed(1)
st = MarketState("BTCUSDT", 1, 0.1)
now = int(time.time() * 1000) // 60000 * 60000
px, kl = 65000.0, []
for i in range(120, 0, -1):
    o = px; px += random.uniform(-15, 15); kl.append([now - i * 60000, o, max(o, px) + 5, min(o, px) - 5, px, 10])
st.seed(kl, [], {"lastPrice": px, "price24hPcnt": 0.01, "highPrice24h": px + 500, "lowPrice24h": px - 500,
                 "fundingRate": 0.0001, "openInterest": 1e5}, [], 1.0)
t0 = now - 40 * 60000
for k in range(40000):
    ts = t0 + k * 60
    p = px + random.gauss(0, 25)
    st.add_trade(ts, round(p, 1), random.random() * 0.5, random.choice(["Buy", "Sell", "Buy"]), f"x{k}")
st.apply_book("snapshot", {"b": [[px - i * .5, random.random() * (50 if i == 20 else 3)] for i in range(1, 200)],
                          "a": [[px + i * .5, random.random() * 3] for i in range(1, 200)]})
for _ in range(5):
    S.compute(st); time.sleep(1.05)
s = st.snapshot
print("regime", s["reg"]["name"], "bucket", st.bucket, "POC", s["prof_s"]["poc"], "alerts", len(st.alerts))
for a in list(st.alerts)[:5]:
    print(" ", a["label"], a["agent"], a["conf"], "rr", a["rr"])
main_fig(s, "BTCUSDT"); depth_fig(s); heat_fig(st); alert_cards(st, s["reg"]); risk_card(st)
print("SMOKE OK")
