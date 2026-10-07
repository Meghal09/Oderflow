# Bybit Order Flow

Real-time order-flow terminal for Bybit USDT perpetuals: footprint, CVD, volume profile,
order-book analytics, smart-money detection, regime-gated signals and risk setups.
FastAPI backend + Plotly Dash UI.

![preview](docs/dashboard_preview.png)
*Layout preview rendered from synthetic data.*

## Features
- Bybit V5 REST + WebSocket (trades, orderbook.200, tickers, klines), auto-reconnect
- Footprint with diagonal imbalances, stacked clusters, aggressive buyers/sellers
- Session + rolling CVD with divergence detection
- Volume profile: POC, VAH/VAL, HVN/LVN
- Depth heatmap, liquidity walls/shifts, absorption, icebergs, sweeps, stop hunts, exhaustion, trapped traders
- AlgoDesk agent routing (REGIME -> FLOW / LIQ / CONTRA / RANGE / OIDIV / FUND) with entry zone, stop, ATR targets, R/R

> Analysis only - it never places orders. Not financial advice. Paper-trade before relying on signals.

## Run locally
```bash
cp .env.example .env        # add a READ-ONLY Bybit key (optional: public data works without)
pip install -r requirements.txt
uvicorn main:app --port 8050 --workers 1     # open http://localhost:8050
```
Keep `--workers 1`: market state lives in process memory.

## Deploy with Cloudflare (Tunnel + Access)
Cloudflare Pages/Workers cannot host this app (it needs a long-running Python process with
persistent WebSockets). Run it on any VPS / home server and expose it with **Cloudflare Tunnel**:

1. Push this repo to GitHub, clone it on your server (needs Docker).
2. Cloudflare dashboard -> **Zero Trust -> Networks -> Tunnels -> Create tunnel** (Cloudflared).
   Copy the **tunnel token**.
3. In the tunnel, add a **Public hostname**: e.g. `flow.yourdomain.com` -> Service `HTTP` -> `app:8050`.
4. On the server:
   ```bash
   cp .env.example .env     # fill BYBIT_API_KEY / SECRET and CLOUDFLARE_TUNNEL_TOKEN
   docker compose up -d --build
   ```
5. **Protect it**: Zero Trust -> Access -> Applications -> Add self-hosted app for
   `flow.yourdomain.com`, policy = your email only. The app has no login of its own.

Notes
- Bybit blocks some regions (e.g. US IPs). Choose a VPS location accordingly.
- Use a **read-only** API key; never commit `.env`.
- Update: `git pull && docker compose up -d --build`.

## API
`/api/health` `/api/instruments` `/api/alerts` `/api/snapshot`

## Tests
`python tests/smoke_test.py` (offline, synthetic tape). CI runs it on every push.
