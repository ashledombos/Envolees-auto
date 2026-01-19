#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration management with Pydantic validation
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Literal
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings


class GeneralConfig(BaseModel):
    risk_percent: float = Field(default=0.5, ge=0.1, le=5.0)
    default_rr_ratio: float = Field(default=2.5, ge=0.5, le=10.0)
    order_timeout_candles: int = Field(default=4, ge=1, le=20)
    candle_timeframe_minutes: int = Field(default=240)
    timezone: str = Field(default="Europe/Paris")


class WebhookConfig(BaseModel):
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=5000)
    secret_token: str = Field(default="CHANGE_ME")
    allowed_ips: List[str] = Field(default_factory=list)


class CTraderBrokerConfig(BaseModel):
    enabled: bool = True
    type: Literal["ctrader"] = "ctrader"
    name: str = "cTrader"
    is_demo: bool = True
    client_id: str = ""
    client_secret: str = ""
    access_token: str = ""
    account_id: Optional[int] = None
    instruments_mapping: Dict[str, int] = Field(default_factory=dict)


class TradeLockerBrokerConfig(BaseModel):
    enabled: bool = True
    type: Literal["tradelocker"] = "tradelocker"
    name: str = "TradeLocker"
    is_demo: bool = True
    email: str = ""
    password: str = ""
    server: str = "GFTTL"
    instruments_mapping: Dict[str, str] = Field(default_factory=dict)


class InstrumentConfig(BaseModel):
    pip_value: float = 0.0001
    lot_size: float = 100000
    min_lot: float = 0.01
    max_lot: float = 100
    session_model: str = "24x5"
    candle_phase_minutes: int = -120


class NotificationChannelConfig(BaseModel):
    type: str
    enabled: bool = False
    config: Dict = Field(default_factory=dict)


class NotificationsConfig(BaseModel):
    enabled: bool = True
    on_order_placed: bool = True
    on_order_expired: bool = True
    on_error: bool = True
    channels: List[NotificationChannelConfig] = Field(default_factory=list)


class AppConfig(BaseModel):
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    brokers: Dict[str, dict] = Field(default_factory=dict)
    instruments: Dict[str, InstrumentConfig] = Field(default_factory=dict)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    
    def get_broker_config(self, broker_id: str) -> Optional[dict]:
        """Get broker configuration by ID"""
        return self.brokers.get(broker_id)
    
    def get_enabled_brokers(self) -> Dict[str, dict]:
        """Get all enabled brokers"""
        return {k: v for k, v in self.brokers.items() if v.get("enabled", False)}
    
    def get_instrument_config(self, symbol: str) -> Optional[InstrumentConfig]:
        """Get instrument configuration by symbol"""
        return self.instruments.get(symbol)


# Global config instance
_config: Optional[AppConfig] = None
_config_path: Optional[Path] = None


def get_config_path() -> Path:
    """Determine config file path"""
    # 1. Environment variable
    env_path = os.environ.get("TRADING_CONFIG_PATH")
    if env_path:
        return Path(env_path)
    
    # 2. Current directory
    cwd_config = Path.cwd() / "config" / "settings.json"
    if cwd_config.exists():
        return cwd_config
    
    # 3. Script directory
    script_dir = Path(__file__).parent.parent
    script_config = script_dir / "config" / "settings.json"
    if script_config.exists():
        return script_config
    
    # 4. Default (may not exist)
    return cwd_config


def load_config(config_path: Optional[Path] = None, reload: bool = False) -> AppConfig:
    """Load and validate configuration"""
    global _config, _config_path
    
    if _config is not None and not reload:
        return _config
    
    path = config_path or get_config_path()
    _config_path = path
    
    if not path.exists():
        print(f"⚠️  Config file not found: {path}")
        print("   Creating default config. Please edit it with your credentials.")
        
        # Create directory if needed
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Copy example config
        example_path = path.parent / "settings.example.json"
        if example_path.exists():
            import shutil
            shutil.copy(example_path, path)
        else:
            # Create minimal config
            _config = AppConfig()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(_config.model_dump(), f, indent=2)
            return _config
    
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Override with environment variables
    data = _apply_env_overrides(data)
    
    _config = AppConfig(**data)
    return _config


def _apply_env_overrides(data: dict) -> dict:
    """Apply environment variable overrides to config"""
    
    # Webhook
    if os.environ.get("WEBHOOK_SECRET"):
        data.setdefault("webhook", {})["secret_token"] = os.environ["WEBHOOK_SECRET"]
    if os.environ.get("WEBHOOK_PORT"):
        data.setdefault("webhook", {})["port"] = int(os.environ["WEBHOOK_PORT"])
    
    # cTrader (FTMO)
    if os.environ.get("CT_CLIENT_ID"):
        data.setdefault("brokers", {}).setdefault("ftmo_ctrader", {})["client_id"] = os.environ["CT_CLIENT_ID"]
    if os.environ.get("CT_CLIENT_SECRET"):
        data.setdefault("brokers", {}).setdefault("ftmo_ctrader", {})["client_secret"] = os.environ["CT_CLIENT_SECRET"]
    if os.environ.get("CT_ACCESS_TOKEN"):
        data.setdefault("brokers", {}).setdefault("ftmo_ctrader", {})["access_token"] = os.environ["CT_ACCESS_TOKEN"]
    if os.environ.get("CT_ACCOUNT_ID"):
        data.setdefault("brokers", {}).setdefault("ftmo_ctrader", {})["account_id"] = int(os.environ["CT_ACCOUNT_ID"])
    
    # TradeLocker (GFT)
    if os.environ.get("TL_EMAIL"):
        data.setdefault("brokers", {}).setdefault("gft_tradelocker", {})["email"] = os.environ["TL_EMAIL"]
    if os.environ.get("TL_PASSWORD"):
        data.setdefault("brokers", {}).setdefault("gft_tradelocker", {})["password"] = os.environ["TL_PASSWORD"]
    if os.environ.get("TL_SERVER"):
        data.setdefault("brokers", {}).setdefault("gft_tradelocker", {})["server"] = os.environ["TL_SERVER"]
    
    return data


def save_config(config: Optional[AppConfig] = None, path: Optional[Path] = None):
    """Save configuration to file"""
    global _config, _config_path
    
    cfg = config or _config
    p = path or _config_path or get_config_path()
    
    if cfg is None:
        raise ValueError("No config to save")
    
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cfg.model_dump(), f, indent=2, ensure_ascii=False)


def get_config() -> AppConfig:
    """Get current config (load if needed)"""
    global _config
    if _config is None:
        return load_config()
    return _config
