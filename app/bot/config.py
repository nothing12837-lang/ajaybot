"""
Configuration loader for AjayBot - YAML based with Pydantic models
"""
import os
import yaml
from pathlib import Path
from typing import Optional, List
from pydantic import BaseModel, Field
from dataclasses import dataclass


class DeltaConfig(BaseModel):
    base_url: str = "https://api.india.delta.exchange"
    api_key: str = ""
    api_secret: str = ""
    testnet: bool = False
    leverage: int = 20


class SymbolConfig(BaseModel):
    symbol: str
    resolution: str = "5m"
    htf_resolution: str = "15m"
    lookback: int = 200
    risk_per_trade: float = 0.02
    max_concurrent: int = 2
    min_confidence: float = 0.15
    contract_size: float = 1
    min_contracts: float = 1


class RiskConfig(BaseModel):
    max_daily_loss_pct: float = 0.05
    max_dd_kill_pct: float = 0.20
    max_position_pct: float = 0.25
    max_correlated_risk_pct: float = 0.10
    consecutive_loss_pause: int = 4
    consecutive_loss_pause_hours: int = 2
    paper_equity: float = 1000.0


class TelegramConfig(BaseModel):
    enabled: bool = True
    bot_token: str = ""
    chat_id: str = ""
    alert_signals: bool = True
    alert_trades: bool = True
    alert_risk: bool = True
    heartbeat_hours: int = 4


class WebUIConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    password: str = "ajaybot2026"
    jwt_secret: str = "ajaybot-secret-change-me"
    jwt_expire_hours: int = 24


class AdaptiveConfig(BaseModel):
    enabled: bool = True
    target_accuracy: float = 0.75
    target_sharpe: float = 1.5
    target_max_dd: float = 0.10
    optimization_interval_hours: int = 2
    min_trades_for_optimization: int = 20
    exploration_rate: float = 0.2
    confidence_scaling: bool = True
    volatility_scaling: bool = True
    kelly_fraction: float = 0.3


class OptimizerConfig(BaseModel):
    enabled: bool = True
    interval_hours: int = 2
    lookback_days: int = 7
    min_trades: int = 30


class Config(BaseModel):
    mode: str = "paper"
    delta: DeltaConfig = DeltaConfig()
    symbols: List[SymbolConfig] = []
    risk: RiskConfig = RiskConfig()
    telegram: TelegramConfig = TelegramConfig()
    webui: WebUIConfig = WebUIConfig()
    data_dir: str = "data"
    adaptive: AdaptiveConfig = AdaptiveConfig()
    optimizer: OptimizerConfig = OptimizerConfig()
    gemini_api_key: str = ""


_settings: Optional[Config] = None


def load_config(config_path: str = "config/config.yaml") -> Config:
    global _settings
    path = Path(config_path)
    if not path.exists():
        path = Path(__file__).parent.parent / "config" / "config.yaml"
    with open(path, 'r') as f:
        data = yaml.safe_load(f) or {}

    # Override from environment variables
    tg = data.setdefault("telegram", {})
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        tg["bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN")
    if os.environ.get("TELEGRAM_ALLOWED_USERS"):
        tg["chat_id"] = os.environ.get("TELEGRAM_ALLOWED_USERS").split(",")[0].strip()
    elif os.environ.get("TELEGRAM_CHAT_ID"):
        tg["chat_id"] = os.environ.get("TELEGRAM_CHAT_ID")
    elif not tg.get("chat_id"):
        tg["chat_id"] = "5238068527"

    delta = data.setdefault("delta", {})
    if os.environ.get("DELTA_API_KEY"):
        delta["api_key"] = os.environ.get("DELTA_API_KEY")
    if os.environ.get("DELTA_API_SECRET"):
        delta["api_secret"] = os.environ.get("DELTA_API_SECRET")

    if os.environ.get("GEMINI_API_KEY"):
        data["gemini_api_key"] = os.environ.get("GEMINI_API_KEY")

    _settings = Config(**data)
    return _settings


def get_settings() -> Config:
    global _settings
    if _settings is None:
        _settings = load_config()
    return _settings


def get_symbol_config(symbol: str) -> Optional[SymbolConfig]:
    settings = get_settings()
    for s in settings.symbols:
        if s.symbol == symbol:
            return s
    return None