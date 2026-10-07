"""Dash UI: candles / footprint / volume profile / CVD / depth + alerts + risk panel."""
from datetime import datetime, timezone

import numpy as np
import plotly.graph_objects as go
from dash import Dash, Input, Output, dcc, html
from plotly.subplots import make_subplots

from config import cfg
from state import rnd

G, R, B, Y = "#26a69a", "#ef5350", "#4fc3f7", "#ffd54f"
f3 = lambda x: f"{x:.3g}"  # noqa
dt = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).replace(tzinfo=None)  # noqa


def empty(msg="Waiting for data..."):
    fig = go.Figure()
    fig.update_layout(template="plotly_dark", annotations=[dict(text=msg, showarrow=False, font_size=18)],
                      paper_bgcolor="#0e1117", plot_bgcolor="#0e1117")
    return fig


def main_fig(s, symbol):
    v, bucket = s["v"], s["v"]["bucket"]
    n = min(80, len(v["t"]))
    t = [dt(x) for x in v["t"][-n:]]
    fig = make_subplots(rows=3, cols=2, column_widths=[0.84, 0.16], row_heights=[0.32, 0.44, 0.24],
                        vertical_spacing=0.045, horizontal_spacing=0.01)
    # ---- 1) candles
    fig.add_trace(go.Candlestick(x=t, open=v["o"][-n:], high=v["h"][-n:], low=v["l"][-n:], close=v["c"][-n:],
                                 increasing_line_color=G, decreasing_line_color=R, name=symbol), 1, 1)
    p = s["prof_s"]
    if p:
        for y, nm, c in ((p["poc"], "POC", Y), (p["vah"], "VAH", B), (p["val"], "VAL", B)):
            fig.add_hline(y=y, line_dash="dot", line_color=c, line_width=1, annotation_text=nm, row=1, col=1)
        fig.add_trace(go.Bar(x=p["vols"], y=p["prices"], orientation="h", name="Profile",
                             marker_color=[Y if q == p["poc"] else "#607d8b" for q in p["prices"]]), 1, 2)
        for q in p["hvn"]:
            fig.add_hline(y=q, line_color="rgba(255,213,79,.25)", row=1, col=2)
        for q in p["lvn"]:
            fig.add_hline(y=q, line_color="rgba(239,83,80,.35)", line_dash="dash", row=1, col=2)
    for dv in s["div"]:
        fig.add_annotation(x=t[min(dv["i"] - (len(v["t"]) - n), n - 1)] if dv["i"] >= len(v["t"]) - n else t[0],
                           y=dv["price"], text="▲ div" if dv["kind"] == "bullish" else "▼ div",
                           font_color=G if dv["kind"] == "bullish" else R, showarrow=False, row=1, col=1)
    # ---- 2) footprint
    vis = v["t"][-cfg.fp_candles:]
    allp = [q for x in vis for q in v["fp"].get(x, {})]
    if allp:
        lo, hi = min(allp), max(allp)
        if (hi - lo) / bucket > 70:
            mid = s["last"]
            lo, hi = rnd(mid - 35 * bucket, bucket), rnd(mid + 35 * bucket, bucket)
        levels = [rnd(lo + i * bucket, bucket) for i in range(int(round((hi - lo) / bucket)) + 1)]
        idx = {q: i for i, q in enumerate(levels)}
        z = np.full((len(levels), len(vis)), np.nan)
        txt = [["" for _ in vis] for _ in levels]
        ox, oy, ocol, ax, ay, acol = [], [], [], [], [], []
        for j, x in enumerate(vis):
            lab = dt(x).strftime("%H:%M")
            for q, (b, a) in v["fp"].get(x, {}).items():
                if q in idx:
                    z[idx[q], j] = a - b
                    txt[idx[q]][j] = f"{f3(b)}×{f3(a)}"
            im = s["imb"].get(x)
            if im:
                for q in im["buy"]:
                    ox.append(lab); oy.append(q); ocol.append(G)
                for q in im["sell"]:
                    ox.append(lab); oy.append(q); ocol.append(R)
                for q in im["agg_buy"]:
                    ax.append(lab); ay.append(q); acol.append("#00e5ff")
                for q in im["agg_sell"]:
                    ax.append(lab); ay.append(q); acol.append("#ff9100")
        labs = [dt(x).strftime("%H:%M") for x in vis]
        zm = max(np.nanmax(np.abs(z)), 1e-9) if np.isfinite(z).any() else 1
        fig.add_trace(go.Heatmap(x=labs, y=levels, z=z, text=txt, texttemplate="%{text}", textfont_size=9,
                                 colorscale="RdYlGn", zmid=0, zmin=-zm, zmax=zm, showscale=False, xgap=2, ygap=1,
                                 hovertemplate="%{x} %{y}<br>bid×ask %{text}<br>Δ %{z:.3g}<extra></extra>",
                                 name="Footprint"), 2, 1)
        fig.add_trace(go.Scatter(x=ox, y=oy, mode="markers", marker=dict(symbol="square-open", size=15,
                                 color=ocol, line_width=2), name="Imbalance", hoverinfo="skip"), 2, 1)
        fig.add_trace(go.Scatter(x=ax, y=ay, mode="markers", marker=dict(symbol="star", size=9, color=acol),
                                 name="Aggressive buyer(cyan)/seller(orange)", hoverinfo="skip"), 2, 1)
        fig.update_xaxes(type="category", row=2, col=1)
        fig.update_yaxes(range=[lo - bucket, hi + bucket], row=2, col=1)
        pw = s["prof_w"]
        if pw:
            fig.add_trace(go.Bar(x=pw["vols"], y=pw["prices"], orientation="h", showlegend=False,
                                 marker_color=[Y if q == pw["poc"] else "#607d8b" for q in pw["prices"]]), 2, 2)
            fig.update_yaxes(range=[lo - bucket, hi + bucket], row=2, col=2)
    # ---- 3) CVD
    fig.add_trace(go.Scatter(x=t, y=s["sess"][-n:], name="Session CVD", line_color=B), 3, 1)
    fig.add_trace(go.Scatter(x=t, y=s["roll"][-n:], name=f"Rolling CVD ({cfg.roll_candles})", line_color=Y), 3, 1)
    fig.add_trace(go.Bar(x=t, y=s["d"][-n:], name="Δ/candle", marker_color=[G if x >= 0 else R for x in s["d"][-n:]],
                         opacity=.35), 3, 1)
    fig.update_xaxes(rangeslider_visible=False)
    fig.update_yaxes(matches="y", row=1, col=2, showticklabels=False)
    fig.update_layout(template="plotly_dark", paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", height=900,
                      margin=dict(l=50, r=10, t=30, b=20), uirevision=symbol, showlegend=True,
                      legend=dict(orientation="h", y=1.04, font_size=10))
    return fig


def depth_fig(s):
    b = s["book"]
    v = s["v"]
    if not b:
        return empty("No book")
    mid = b["mid"]
    bids = sorted(((p, q) for p, q in v["bids"].items() if p >= mid * .995), reverse=True)
    asks = sorted((p, q) for p, q in v["asks"].items() if p <= mid * 1.005)
    cb, ca = np.cumsum([q for _, q in bids]), np.cumsum([q for _, q in asks])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=cb, y=[p for p, _ in bids], fill="tozerox", line_color=G, name="Bids", line_shape="hv"))
    fig.add_trace(go.Scatter(x=ca, y=[p for p, _ in asks], fill="tozerox", line_color=R, name="Asks", line_shape="hv"))
    for (side, p), q in b["walls"].items():
        fig.add_hline(y=p, line_color=G if side == "bid" else R, line_dash="dot", line_width=1,
                      annotation_text=f"wall {f3(q)}", annotation_font_size=9)
    fig.update_layout(template="plotly_dark", paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", height=330,
                      margin=dict(l=40, r=5, t=25, b=20), title=dict(text="Live depth", font_size=12), showlegend=False)
    return fig


def heat_fig(st):
    h = list(st.book_hist)[-240:]
    if len(h) < 3:
        return empty("Collecting book history...")
    z = np.array([r for _, _, r in h]).T
    fig = go.Figure(go.Heatmap(x=[dt(t).strftime("%H:%M:%S") for t, _, _ in h],
                               y=np.linspace(-50, 50, 40), z=np.log1p(z), colorscale="Inferno", showscale=False,
                               hovertemplate="%{x}<br>%{y:.0f} bps<extra></extra>"))
    fig.update_layout(template="plotly_dark", paper_bgcolor="#0e1117", height=260, margin=dict(l=40, r=5, t=25, b=20),
                      title=dict(text="Depth heatmap (bps from mid, log size)", font_size=12))
    return fig


def alert_cards(st, reg):
    out = []
    for a in list(st.alerts)[:14]:
        col = G if a["dir"] > 0 else R
        out.append(html.Div([
            html.Div([html.B(a["label"], style={"color": col}),
                      html.Span(f"  {a['agent']} · {a['conf']:.0%}" + ("" if a["regime_ok"] else " · counter-regime"),
                                style={"opacity": .7, "fontSize": 11})]),
            html.Div(f"{datetime.fromtimestamp(a['ts'] / 1000).strftime('%H:%M:%S')} · {a['note']}",
                     style={"fontSize": 11, "opacity": .75})],
            style={"borderLeft": f"3px solid {col}", "padding": "3px 8px", "margin": "4px 0",
                   "opacity": 1 if a["regime_ok"] else .55}))
    return out or [html.Div("No alerts yet", style={"opacity": .6})]


def risk_card(st):
    ok = [a for a in st.alerts if a["rr"] >= cfg.min_rr and a["regime_ok"]]
    if not ok:
        return html.Div("No actionable setup", style={"opacity": .6})
    a = max(ok[:8], key=lambda x: x["conf"])
    col = G if a["dir"] > 0 else R
    row = lambda k, vv: html.Div([html.Span(k, style={"opacity": .7}), html.Span(vv, style={"float": "right"})])  # noqa
    return html.Div([
        html.B(f"{'LONG' if a['dir'] > 0 else 'SHORT'} · {a['label']}", style={"color": col}),
        row("Entry zone", f"{a['entry_lo']:.6g} – {a['entry_hi']:.6g}"),
        row("Stop loss", f"{a['stop']:.6g}  ({a['risk_pct']:.2f}%)" + (" ⚠ > agent cap" if a["sl_cap_exceeded"] else "")),
        row("Targets (vol-adj.)", " / ".join(f"{x:.6g}" for x in a["targets"])),
        row("Risk / Reward", f"1 : {a['rr']}"),
        row("Max size (agent)", f"{a['size_pct']}% portfolio"),
        row("Agent / Regime", f"{a['agent']} / {a['regime']}")], style={"fontSize": 12, "lineHeight": "1.6"})


def build_dash(engine):
    app = Dash(__name__, requests_pathname_prefix="/", title="Bybit Order Flow")
    syms = sorted(engine.instruments)
    card = {"background": "#161b22", "padding": 8, "borderRadius": 6, "marginBottom": 8}
    app.layout = html.Div(style={"background": "#0e1117", "color": "#ddd", "padding": 8, "fontFamily": "sans-serif"}, children=[
        html.Div(style={"display": "flex", "gap": 12, "alignItems": "center"}, children=[
            html.Div(dcc.Dropdown(syms, cfg.symbol, id="sym", clearable=False, style={"color": "#000"}), style={"width": 220}),
            html.Div(dcc.Dropdown([{"label": f"{x}m", "value": x} for x in ("1", "3", "5", "15", "30")], cfg.tf,
                                  id="tf", clearable=False, style={"color": "#000"}), style={"width": 90}),
            html.Div(id="status", style={"fontSize": 12})]),
        dcc.Interval(id="tick", interval=1000),
        html.Div(style={"display": "flex", "gap": 8}, children=[
            html.Div(dcc.Graph(id="main", config={"displaylogo": False}), style={"flex": "1 1 74%"}),
            html.Div(style={"flex": "1 1 26%", "minWidth": 320}, children=[
                html.Div(id="risk", style=card), dcc.Graph(id="depth"), dcc.Graph(id="heat"),
                html.Div(id="alerts", style={**card, "maxHeight": 330, "overflowY": "auto"})])])])

    @app.callback(Output("main", "figure"), Output("depth", "figure"), Output("heat", "figure"),
                  Output("alerts", "children"), Output("risk", "children"), Output("status", "children"),
                  Input("tick", "n_intervals"), Input("sym", "value"), Input("tf", "value"))
    def refresh(_, sym, tf):
        try:
            engine.switch(sym, tf)
            st = engine.state
            s = st.snapshot
            if not s or s["v"]["t"][-1:] == []:
                return empty(), empty(), empty(), [], "", "loading..."
            r = s["reg"]
            status = (f"{engine.auth['msg']} | WS {engine.ws_status} | {st.symbol} {s['last']:.6g} | bucket {st.bucket} | "
                      f"REGIME {r['name'].upper()} ({r['conf']:.0%}) · 24h {r['chg24']:+.2f}% · ATR {s['atr']:.4g} | "
                      f"funding {st.ticker.get('fundingRate', 0) * 100:.4f}% · OI {st.ticker.get('openInterest', 0):,.0f}")
            return (main_fig(s, st.symbol), depth_fig(s), heat_fig(st), alert_cards(st, r), risk_card(st), status)
        except Exception as e:  # noqa
            import logging
            logging.getLogger("dash").exception("refresh failed")
            return empty(str(e)), empty(), empty(), [], "", f"error: {e}"

    return app
