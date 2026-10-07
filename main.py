"""FastAPI backend + mounted Dash UI. Run with ONE worker: uvicorn main:app --host 0.0.0.0 --port 8050"""
import logging
from contextlib import asynccontextmanager

from a2wsgi import WSGIMiddleware
from fastapi import FastAPI, HTTPException

from dashboard import build_dash
from engine import Engine

logging.basicConfig(level=logging.INFO)
engine = Engine()


@asynccontextmanager
async def lifespan(app):
    engine.start()
    app.mount("/", WSGIMiddleware(build_dash(engine).server))
    yield


app = FastAPI(title="Bybit Order Flow", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"auth": engine.auth, "ws": engine.ws_status, "symbol": engine.state.symbol if engine.state else None}


@app.get("/api/instruments")
def instruments():
    return list(engine.instruments.values())


@app.get("/api/alerts")
def alerts(limit: int = 50):
    if not engine.state:
        raise HTTPException(503, "engine not ready")
    return list(engine.state.alerts)[:limit]


@app.get("/api/snapshot")
def snapshot():
    s = engine.state.snapshot if engine.state else None
    if not s:
        raise HTTPException(503, "no data yet")
    p = s["prof_s"] or {}
    return {"symbol": engine.state.symbol, "last": s["last"], "regime": s["reg"], "atr": s["atr"],
            "poc": p.get("poc"), "vah": p.get("vah"), "val": p.get("val"),
            "session_cvd": float(s["sess"][-1]), "rolling_cvd": float(s["roll"][-1])}
