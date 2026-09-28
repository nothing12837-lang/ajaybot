"""
Web UI - FastAPI dashboard for AjayBot
"""
import asyncio
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
# from fastapi.templating import Jinja2Templates  # Not used
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import jwt

from bot.config import get_settings, Config

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.bot_state = {}
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        await websocket.send_json({"type": "state", "data": self.bot_state})
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        dead = []
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except:
                dead.append(conn)
        for conn in dead:
            self.disconnect(conn)
    
    def update_state(self, key: str, value):
        self.bot_state[key] = value
        asyncio.create_task(self.broadcast({"type": "state", "data": {key: value}}))


manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="AjayBot Trading Dashboard",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
# templates = Jinja2Templates(directory=BASE_DIR / "templates")  # Not used, index.html served from static


def create_token(data: dict) -> str:
    settings = get_settings()
    return jwt.encode(data, settings.webui.jwt_secret, algorithm="HS256")


def verify_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.webui.jwt_secret, algorithms=["HS256"])


class LoginRequest(BaseModel):
    password: str


class ConfigUpdateRequest(BaseModel):
    config: dict


_bot_instance = None


def get_bot_instance():
    global _bot_instance
    return _bot_instance


def set_bot_instance(bot):
    global _bot_instance
    _bot_instance = bot


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/status")
async def status():
    bot = get_bot_instance()
    if bot:
        return bot.get_status()
    return {"state": "stopped"}


@app.get("/api/positions")
async def positions():
    bot = get_bot_instance()
    if bot:
        return {sym: {
            "symbol": pos.symbol,
            "side": pos.side,
            "size": pos.size,
            "entry_price": pos.entry_price,
            "entry_time": pos.entry_time,
            "stop_loss": pos.stop_loss,
            "take_profit_1": pos.take_profit_1,
            "take_profit_2": pos.take_profit_2,
            "trail_price": pos.trail_price,
            "breakeven": pos.breakeven,
            "partial_filled": pos.partial_filled,
            "unrealized_pnl": pos.unrealized_pnl,
            "realized_pnl": pos.realized_pnl,
            "regime": pos.regime,
            "confidence": pos.confidence,
            "contract_size": pos.contract_size,
        } for sym, pos in bot._positions.items()}
    return {}


@app.get("/api/risk")
async def risk():
    bot = get_bot_instance()
    if bot:
        dd = (bot._peak_equity - bot._current_equity) / bot._peak_equity if bot._peak_equity > 0 else 0
        daily_limit = bot.config.risk.max_daily_loss_pct * bot.config.risk.paper_equity
        return {
            "daily_used_pct": (-bot._daily_pnl / daily_limit * 100) if daily_limit > 0 else 0,
            "dd_used_pct": (dd / bot.config.risk.max_dd_kill_pct * 100) if bot.config.risk.max_dd_kill_pct > 0 else 0,
            "consecutive_losses": bot._consecutive_losses,
            "kill_switch": getattr(bot.risk_manager, 'kill_switch', False),
            "peak_equity": bot._peak_equity,
            "current_equity": bot._current_equity,
        }
    return {}


@app.get("/api/chart/{symbol}")
async def chart(symbol: str):
    from bot.bot import candle_store
    from bot.indicators import all_indicators
    from bot.config import get_symbol_config
    
    sym_config = get_symbol_config(symbol)
    if not sym_config:
        return {"candles": [], "markers": []}
    df = candle_store.get_df(symbol, sym_config.resolution, lookback=500)
    if df.empty:
        return {"candles": [], "markers": []}
    
    df = all_indicators(df, sym_config.model_dump())
    
    candles = []
    for idx, row in df.iterrows():
        candles.append({
            "time": int(idx.timestamp()),
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
        })
    
    return {"candles": candles, "markers": []}


@app.get("/api/trades")
async def trades(limit: int = 100):
    return []


@app.get("/api/stats/{period}")
async def stats(period: str = "today"):
    return {}


@app.get("/api/signals")
async def signals(limit: int = 50):
    bot = get_bot_instance()
    if bot and bot.signal_engine:
        out = []
        for s in bot.signal_engine.signal_history[-limit:]:
            out.append({
                "symbol": s.symbol,
                "timestamp": s.timestamp,
                "side": s.side.value,
                "confidence": s.confidence,
                "price": s.price,
                "regime": s.regime,
                "explanation": s.explanation,
                "agents": s.agents,
            })
        return out
    return []


@app.post("/api/login")
async def login(req: LoginRequest):
    settings = get_settings()
    if req.password == settings.webui.password:
        token = create_token({"sub": "admin", "exp": time.time() + settings.webui.jwt_expire_hours * 3600})
        return {"token": token}
    raise HTTPException(401, "Invalid password")


@app.get("/api/config")
async def get_config():
    settings = get_settings()
    return settings.model_dump()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def broadcast_update(event_type: str, data: dict):
    await manager.broadcast({"type": event_type, "data": data})


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(app, host=settings.webui.host, port=settings.webui.port)