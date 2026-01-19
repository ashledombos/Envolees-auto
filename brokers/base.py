#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Base broker interface and common types
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass
class OrderRequest:
    """Order request to be sent to broker"""
    symbol: str                          # Unified symbol (e.g., "EURUSD")
    side: OrderSide
    order_type: OrderType
    volume: float                        # In lots
    
    # Price levels
    entry_price: Optional[float] = None  # Required for LIMIT/STOP
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    
    # Expiration
    expiry_timestamp_ms: Optional[int] = None
    
    # Metadata
    label: str = ""
    comment: str = ""
    magic_number: Optional[int] = None
    
    # Calculated fields (filled by broker)
    broker_symbol: Optional[str] = None  # Broker-specific symbol
    broker_volume: Optional[int] = None  # Broker-specific volume unit


@dataclass
class OrderResult:
    """Result of an order operation"""
    success: bool
    order_id: Optional[str] = None
    message: str = ""
    error_code: Optional[str] = None
    broker_response: Optional[Any] = None
    
    # Execution details
    fill_price: Optional[float] = None
    fill_volume: Optional[float] = None
    fill_time: Optional[datetime] = None


@dataclass
class Position:
    """Open position"""
    position_id: str
    symbol: str
    side: OrderSide
    volume: float
    entry_price: float
    current_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    profit: Optional[float] = None
    open_time: Optional[datetime] = None


@dataclass
class PendingOrder:
    """Pending order (not yet filled)"""
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    volume: float
    entry_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    created_time: Optional[datetime] = None
    expiry_time: Optional[datetime] = None
    label: str = ""
    comment: str = ""
    
    # For order cleanup
    broker_id: str = ""
    raw_data: Optional[dict] = None


@dataclass
class AccountInfo:
    """Account information"""
    account_id: str
    broker_name: str
    balance: float
    equity: float
    margin_used: float = 0.0
    margin_free: float = 0.0
    currency: str = "USD"
    leverage: int = 100
    is_demo: bool = True


@dataclass
class SymbolInfo:
    """Symbol/instrument information"""
    symbol: str
    broker_symbol: str  # Broker-specific symbol ID
    description: str = ""
    pip_value: float = 0.0001
    pip_size: float = 0.0001
    lot_size: float = 100000
    min_volume: float = 0.01
    max_volume: float = 100
    volume_step: float = 0.01
    tick_size: float = 0.00001
    digits: int = 5
    is_tradable: bool = True


class BaseBroker(ABC):
    """Abstract base class for broker implementations"""
    
    def __init__(self, broker_id: str, config: dict):
        self.broker_id = broker_id
        self.config = config
        self.name = config.get("name", broker_id)
        self.is_demo = config.get("is_demo", True)
        self._connected = False
        self._account_info: Optional[AccountInfo] = None
        self._symbols_cache: Dict[str, SymbolInfo] = {}
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to broker"""
        pass
    
    @abstractmethod
    async def disconnect(self):
        """Disconnect from broker"""
        pass
    
    @abstractmethod
    async def get_account_info(self) -> Optional[AccountInfo]:
        """Get account information"""
        pass
    
    @abstractmethod
    async def get_symbols(self) -> List[SymbolInfo]:
        """Get available symbols"""
        pass
    
    @abstractmethod
    async def get_symbol_info(self, symbol: str) -> Optional[SymbolInfo]:
        """Get info for specific symbol"""
        pass
    
    @abstractmethod
    async def place_order(self, order: OrderRequest) -> OrderResult:
        """Place an order"""
        pass
    
    @abstractmethod
    async def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel a pending order"""
        pass
    
    @abstractmethod
    async def get_pending_orders(self) -> List[PendingOrder]:
        """Get all pending orders"""
        pass
    
    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """Get all open positions"""
        pass
    
    def map_symbol(self, unified_symbol: str) -> Optional[str]:
        """Map unified symbol to broker-specific symbol"""
        mapping = self.config.get("instruments_mapping", {})
        return mapping.get(unified_symbol)
    
    def reverse_map_symbol(self, broker_symbol: str) -> Optional[str]:
        """Map broker-specific symbol back to unified symbol"""
        mapping = self.config.get("instruments_mapping", {})
        for unified, broker in mapping.items():
            if str(broker) == str(broker_symbol):
                return unified
        return None
    
    def calculate_lot_size(
        self, 
        account_balance: float,
        risk_percent: float,
        stop_loss_pips: float,
        symbol_info: SymbolInfo
    ) -> float:
        """Calculate position size based on risk management"""
        # Risk amount in account currency
        risk_amount = account_balance * (risk_percent / 100)
        
        # Value per pip per lot
        pip_value_per_lot = symbol_info.lot_size * symbol_info.pip_size
        
        # Calculate lots
        lots = risk_amount / (stop_loss_pips * pip_value_per_lot)
        
        # Clamp to min/max and round to step
        lots = max(symbol_info.min_volume, min(lots, symbol_info.max_volume))
        lots = round(lots / symbol_info.volume_step) * symbol_info.volume_step
        
        return round(lots, 2)
    
    def __repr__(self):
        status = "connected" if self._connected else "disconnected"
        return f"<{self.__class__.__name__} {self.name} ({status})>"
