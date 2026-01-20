#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration management with YAML support and Pydantic validation
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field

# Import YAML
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    print("⚠️  PyYAML not installed. Install with: pip install PyYAML")


# =============================================================================
# Configuration Models
# =============================================================================

class GeneralConfig(BaseModel):
    """General trading parameters"""
    risk_percent: float = Field(default=0.5, ge=0.1, le=5.0, description="Risk per trade (%)")
    use_equity: bool = Field(default=True, description="Use equity (True) or balance (False)")
    default_rr_ratio: float = Field(default=2.5, ge=0.5, le=10.0)
    order_timeout_candles: int = Field(default=4, ge=1, le=20)
    candle_timeframe_minutes: int = Field(default=240)


class DelayConfig(BaseModel):
    """Delay between broker executions"""
    enabled: bool = True
    min_ms: int = Field(default=500, ge=0)
    max_ms: int = Field(default=3000, ge=0)


class ExecutionConfig(BaseModel):
    """Order execution settings"""
    delay_between_brokers: DelayConfig = Field(default_factory=DelayConfig)
    broker_order: Optional[List[str]] = None  # Order of execution


class FiltersConfig(BaseModel):
    """Pre-placement filters to protect accounts"""
    min_margin_percent: float = Field(default=30.0, ge=0, le=100)
    max_daily_drawdown_percent: float = Field(default=4.0, ge=0, le=100)
    max_total_drawdown_percent: float = Field(default=9.0, ge=0, le=100)
    max_open_positions: int = Field(default=5, ge=1)
    max_pending_orders: int = Field(default=10, ge=1)
    prevent_duplicate_orders: bool = True


class WebhookConfig(BaseModel):
    """Webhook server configuration"""
    host: str = "0.0.0.0"
    port: int = 5000
    secret_token: str = "CHANGE_ME"
    allowed_ips: List[str] = Field(default_factory=list)


class BrokerLimitsConfig(BaseModel):
    """Per-broker limits override"""
    max_daily_drawdown_percent: Optional[float] = None
    max_total_drawdown_percent: Optional[float] = None
    max_open_positions: Optional[int] = None


class BrokerConfig(BaseModel):
    """Base broker configuration"""
    enabled: bool = True
    type: str  # "ctrader" or "tradelocker"
    name: str = ""
    is_demo: bool = True
    limits: Optional[BrokerLimitsConfig] = None
    
    # cTrader specific
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    auto_refresh_token: bool = True
    
    # TradeLocker specific
    base_url: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    server: Optional[str] = None
    
    # Common
    account_id: Optional[Union[int, str]] = None


class InstrumentConfig(BaseModel):
    """Instrument configuration with broker mapping"""
    pip_size: float = 0.0001
    pip_value_per_lot: Optional[float] = None  # None = calculate dynamically
    contract_size: Optional[float] = None
    quote_currency: Optional[str] = None  # For cross pairs (e.g., "JPY" for EURJPY)


class NotificationsConfig(BaseModel):
    """Notification settings"""
    enabled: bool = False
    on_order_placed: bool = True
    on_order_filled: bool = True
    on_order_cancelled: bool = True
    on_order_error: bool = True
    on_filter_skip: bool = True
    channels: List[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    """Main application configuration"""
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    brokers: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    instruments: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    
    def get_broker_config(self, broker_id: str) -> Optional[Dict[str, Any]]:
        """Get broker configuration by ID"""
        return self.brokers.get(broker_id)
    
    def get_enabled_brokers(self) -> Dict[str, Dict[str, Any]]:
        """Get all enabled brokers"""
        return {k: v for k, v in self.brokers.items() if v.get("enabled", False)}
    
    def get_instrument_symbol(self, tv_symbol: str, broker_id: str) -> Optional[str]:
        """Get broker-specific symbol name for a TradingView symbol"""
        instrument = self.instruments.get(tv_symbol, {})
        return instrument.get(broker_id)
    
    def get_instrument_config(self, tv_symbol: str) -> Optional[Dict[str, Any]]:
        """Get instrument configuration"""
        return self.instruments.get(tv_symbol)
    
    def is_instrument_available(self, tv_symbol: str, broker_id: str) -> bool:
        """Check if instrument is available for a specific broker"""
        instrument = self.instruments.get(tv_symbol, {})
        return broker_id in instrument and instrument[broker_id] is not None
    
    def get_broker_limits(self, broker_id: str) -> FiltersConfig:
        """Get effective limits for a broker (broker-specific or global)"""
        broker = self.brokers.get(broker_id, {})
        broker_limits = broker.get("limits", {}) or {}
        
        # Start with global filters
        limits = self.filters.model_copy()
        
        # Override with broker-specific limits
        if broker_limits.get("max_daily_drawdown_percent") is not None:
            limits.max_daily_drawdown_percent = broker_limits["max_daily_drawdown_percent"]
        if broker_limits.get("max_total_drawdown_percent") is not None:
            limits.max_total_drawdown_percent = broker_limits["max_total_drawdown_percent"]
        if broker_limits.get("max_open_positions") is not None:
            limits.max_open_positions = broker_limits["max_open_positions"]
        
        return limits


# =============================================================================
# Global State
# =============================================================================

_config: Optional[AppConfig] = None
_config_path: Optional[Path] = None


# =============================================================================
# Config Loading Functions
# =============================================================================

def get_config_path() -> Path:
    """Determine config file path (YAML preferred over JSON)"""
    # 1. Environment variable
    env_path = os.environ.get("TRADING_CONFIG_PATH")
    if env_path:
        return Path(env_path)
    
    # 2. Current directory - YAML first
    cwd = Path.cwd()
    for filename in ["settings.yaml", "settings.yml", "settings.json"]:
        config_path = cwd / "config" / filename
        if config_path.exists():
            return config_path
    
    # 3. Script directory
    script_dir = Path(__file__).parent.parent
    for filename in ["settings.yaml", "settings.yml", "settings.json"]:
        config_path = script_dir / "config" / filename
        if config_path.exists():
            return config_path
    
    # 4. Default (YAML preferred)
    return cwd / "config" / "settings.yaml"


def _load_file(path: Path) -> dict:
    """Load configuration file (YAML or JSON)"""
    with open(path, "r", encoding="utf-8") as f:
        if path.suffix in [".yaml", ".yml"]:
            if not YAML_AVAILABLE:
                raise ImportError("PyYAML required for YAML config. Install: pip install PyYAML")
            return yaml.safe_load(f) or {}
        else:
            return json.load(f)


def _save_file(path: Path, data: dict):
    """Save configuration file (YAML or JSON)"""
    with open(path, "w", encoding="utf-8") as f:
        if path.suffix in [".yaml", ".yml"]:
            if not YAML_AVAILABLE:
                raise ImportError("PyYAML required for YAML config")
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        else:
            json.dump(data, f, indent=2, ensure_ascii=False)


def load_config(config_path: Optional[Path] = None, reload: bool = False) -> AppConfig:
    """Load and validate configuration"""
    global _config, _config_path
    
    if _config is not None and not reload:
        return _config
    
    path = config_path or get_config_path()
    _config_path = path
    
    if not path.exists():
        print(f"⚠️  Config file not found: {path}")
        print("   Please copy settings.example.yaml to settings.yaml and edit it.")
        
        # Create directory if needed
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Try to copy example
        for ext in [".yaml", ".yml", ".json"]:
            example_path = path.parent / f"settings.example{ext}"
            if example_path.exists():
                import shutil
                target = path.parent / f"settings{ext}"
                shutil.copy(example_path, target)
                print(f"   Created {target} from example.")
                path = target
                break
        else:
            # Create minimal config
            _config = AppConfig()
            return _config
    
    data = _load_file(path)
    
    # Apply environment variable overrides
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
    if os.environ.get("CT_REFRESH_TOKEN"):
        data.setdefault("brokers", {}).setdefault("ftmo_ctrader", {})["refresh_token"] = os.environ["CT_REFRESH_TOKEN"]
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
    
    _save_file(p, cfg.model_dump())


def get_config() -> AppConfig:
    """Get current config (load if needed)"""
    global _config
    if _config is None:
        return load_config()
    return _config


def update_broker_tokens(broker_id: str, access_token: str, refresh_token: str = None):
    """Update broker tokens in config file (used by auto-refresh)"""
    global _config, _config_path
    
    if _config is None or _config_path is None:
        return
    
    # Reload from file to avoid overwriting other changes
    data = _load_file(_config_path)
    
    if "brokers" in data and broker_id in data["brokers"]:
        data["brokers"][broker_id]["access_token"] = access_token
        if refresh_token:
            data["brokers"][broker_id]["refresh_token"] = refresh_token
        
        _save_file(_config_path, data)
        
        # Update in-memory config
        _config.brokers[broker_id]["access_token"] = access_token
        if refresh_token:
            _config.brokers[broker_id]["refresh_token"] = refresh_token
