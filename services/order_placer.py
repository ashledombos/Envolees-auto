#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Order placement service
Handles order placement across multiple brokers with risk management
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass

from brokers import (
    create_broker, create_all_brokers,
    BaseBroker, OrderRequest, OrderResult,
    OrderSide, OrderType, AccountInfo
)
from utils.notifications import get_notification_service
from config import get_config, AppConfig


@dataclass
class SignalData:
    """Signal data received from TradingView webhook"""
    symbol: str
    side: str  # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float
    
    # Optional fields
    order_type: str = "LIMIT"  # "LIMIT", "STOP", "MARKET"
    validity_bars: int = 1
    atr: Optional[float] = None
    timeframe: str = "H4"
    
    # Metadata
    source: str = "tradingview"
    timestamp: Optional[datetime] = None
    raw_message: Optional[str] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
        
        # Normalize side
        self.side = self.side.upper()
        if self.side in ["BUY", "LONG"]:
            self.side = "LONG"
        elif self.side in ["SELL", "SHORT"]:
            self.side = "SHORT"
    
    @property
    def order_side(self) -> OrderSide:
        return OrderSide.BUY if self.side == "LONG" else OrderSide.SELL
    
    @property
    def broker_order_type(self) -> OrderType:
        ot = self.order_type.upper()
        if ot == "MARKET":
            return OrderType.MARKET
        elif ot == "STOP":
            return OrderType.STOP
        else:
            return OrderType.LIMIT
    
    def calculate_risk_pips(self) -> float:
        """Calculate risk in pips (distance from entry to SL)"""
        return abs(self.entry_price - self.stop_loss)
    
    def calculate_rr_ratio(self) -> float:
        """Calculate risk/reward ratio"""
        risk = self.calculate_risk_pips()
        reward = abs(self.take_profit - self.entry_price)
        return reward / risk if risk > 0 else 0
    
    @classmethod
    def from_webhook(cls, data: dict) -> "SignalData":
        """Create SignalData from webhook payload"""
        return cls(
            symbol=data.get("symbol", ""),
            side=data.get("side", ""),
            entry_price=float(data.get("entry", data.get("entry_price", 0))),
            stop_loss=float(data.get("sl", data.get("stop_loss", 0))),
            take_profit=float(data.get("tp", data.get("take_profit", 0))),
            order_type=data.get("order_type", "LIMIT"),
            validity_bars=int(data.get("validity_bars", data.get("validBars", 1))),
            atr=float(data.get("atr")) if data.get("atr") else None,
            timeframe=data.get("timeframe", "H4"),
            source=data.get("source", "tradingview"),
            raw_message=str(data)
        )


class OrderPlacer:
    """Service for placing orders across multiple brokers"""
    
    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or get_config()
        self.brokers: Dict[str, BaseBroker] = {}
        self._connected = False
    
    async def connect(self) -> bool:
        """Connect to all enabled brokers"""
        self.brokers = create_all_brokers(
            self.config.brokers, 
            enabled_only=True, 
            sync=False
        )
        
        if not self.brokers:
            print("[OrderPlacer] No brokers configured")
            return False
        
        success = True
        for broker_id, broker in self.brokers.items():
            try:
                if await broker.connect():
                    print(f"[OrderPlacer] ✅ Connected to {broker.name}")
                else:
                    print(f"[OrderPlacer] ❌ Failed to connect to {broker.name}")
                    success = False
            except Exception as e:
                print(f"[OrderPlacer] ❌ Error connecting to {broker.name}: {e}")
                success = False
        
        self._connected = success
        return success
    
    async def disconnect(self):
        """Disconnect from all brokers"""
        for broker in self.brokers.values():
            try:
                await broker.disconnect()
            except Exception:
                pass
        self._connected = False
    
    def calculate_position_size(
        self,
        account_balance: float,
        risk_percent: float,
        entry_price: float,
        stop_loss: float,
        pip_value: float = 0.0001,
        lot_size: float = 100000,
        min_lot: float = 0.01,
        max_lot: float = 100
    ) -> float:
        """
        Calculate position size based on risk management.
        
        Args:
            account_balance: Current account balance
            risk_percent: Risk percentage (e.g., 0.5 for 0.5%)
            entry_price: Entry price
            stop_loss: Stop loss price
            pip_value: Value of one pip (e.g., 0.0001 for most forex pairs)
            lot_size: Contract size (e.g., 100000 for standard forex lot)
            min_lot: Minimum lot size
            max_lot: Maximum lot size
        
        Returns:
            Position size in lots
        """
        # Risk amount in account currency
        risk_amount = account_balance * (risk_percent / 100)
        
        # Distance to SL in pips
        sl_distance = abs(entry_price - stop_loss)
        sl_pips = sl_distance / pip_value
        
        # Value per pip per lot
        pip_value_per_lot = lot_size * pip_value
        
        # Calculate lots
        if sl_pips > 0:
            lots = risk_amount / (sl_pips * pip_value_per_lot)
        else:
            lots = min_lot
        
        # Clamp to min/max
        lots = max(min_lot, min(lots, max_lot))
        
        # Round to 2 decimal places
        lots = round(lots, 2)
        
        return lots
    
    def calculate_expiry_timestamp(
        self,
        validity_bars: int,
        timeframe_minutes: int = 240
    ) -> int:
        """Calculate order expiry timestamp in milliseconds"""
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(minutes=validity_bars * timeframe_minutes)
        return int(expiry.timestamp() * 1000)
    
    async def place_signal(
        self,
        signal: SignalData,
        brokers: Optional[List[str]] = None
    ) -> Dict[str, OrderResult]:
        """
        Place orders for a signal across specified brokers.
        
        Args:
            signal: Signal data from TradingView
            brokers: List of broker IDs to use (None = all enabled)
        
        Returns:
            Dict of broker_id -> OrderResult
        """
        if not self._connected:
            await self.connect()
        
        results = {}
        target_brokers = brokers or list(self.brokers.keys())
        
        notification_service = get_notification_service()
        
        for broker_id in target_brokers:
            if broker_id not in self.brokers:
                results[broker_id] = OrderResult(
                    success=False,
                    message=f"Broker {broker_id} not found"
                )
                continue
            
            broker = self.brokers[broker_id]
            
            try:
                result = await self._place_on_broker(broker, signal)
                results[broker_id] = result
                
                # Send notification
                if result.success:
                    notification_service.notify_order_placed(
                        broker=broker.name,
                        symbol=signal.symbol,
                        side=signal.side,
                        order_type=signal.order_type,
                        volume=result.broker_response.get("volume", 0) if result.broker_response else 0,
                        entry_price=signal.entry_price,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        order_id=result.order_id or ""
                    )
                else:
                    notification_service.notify_error(
                        broker=broker.name,
                        message=f"Failed to place {signal.side} on {signal.symbol}",
                        error_details=result.message
                    )
                    
            except Exception as e:
                results[broker_id] = OrderResult(
                    success=False,
                    message=str(e)
                )
                notification_service.notify_error(
                    broker=broker.name,
                    message=f"Error placing order on {signal.symbol}",
                    error_details=str(e)
                )
        
        return results
    
    async def _place_on_broker(
        self,
        broker: BaseBroker,
        signal: SignalData
    ) -> OrderResult:
        """Place order on a single broker"""
        
        # Check if symbol is available
        broker_symbol = broker.map_symbol(signal.symbol)
        if not broker_symbol:
            return OrderResult(
                success=False,
                message=f"Symbol {signal.symbol} not mapped for {broker.name}"
            )
        
        # Get account info for position sizing
        account_info = await broker.get_account_info()
        if not account_info:
            return OrderResult(
                success=False,
                message=f"Could not get account info from {broker.name}"
            )
        
        # Get instrument config
        instrument_config = self.config.get_instrument_config(signal.symbol)
        
        # Calculate position size
        risk_percent = self.config.general.risk_percent
        
        if instrument_config:
            volume = self.calculate_position_size(
                account_balance=account_info.balance,
                risk_percent=risk_percent,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                pip_value=instrument_config.pip_value,
                lot_size=instrument_config.lot_size,
                min_lot=instrument_config.min_lot,
                max_lot=instrument_config.max_lot
            )
        else:
            # Default calculation
            volume = self.calculate_position_size(
                account_balance=account_info.balance,
                risk_percent=risk_percent,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss
            )
        
        # Calculate expiry
        timeframe_minutes = self.config.general.candle_timeframe_minutes
        expiry_ms = self.calculate_expiry_timestamp(
            signal.validity_bars,
            timeframe_minutes
        )
        
        # Create order request
        order = OrderRequest(
            symbol=signal.symbol,
            side=signal.order_side,
            order_type=signal.broker_order_type,
            volume=volume,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            expiry_timestamp_ms=expiry_ms,
            label=f"TV-{signal.symbol[:8]}",
            comment=f"Signal {signal.timeframe} {signal.side}"
        )
        
        print(f"[OrderPlacer] Placing on {broker.name}: {signal.side} {volume} lots {signal.symbol} @ {signal.entry_price}")
        print(f"              SL: {signal.stop_loss}, TP: {signal.take_profit}, Expiry: {expiry_ms}")
        
        # Place order
        result = await broker.place_order(order)
        
        # Add volume to result for notifications
        if result.success:
            if result.broker_response is None:
                result.broker_response = {}
            if isinstance(result.broker_response, dict):
                result.broker_response["volume"] = volume
        
        return result


# Synchronous wrapper for CLI
class OrderPlacerSync:
    """Synchronous wrapper for OrderPlacer"""
    
    def __init__(self, config: Optional[AppConfig] = None):
        self.placer = OrderPlacer(config)
        self._loop = None
    
    def _get_loop(self):
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop
    
    def connect(self) -> bool:
        return self._get_loop().run_until_complete(self.placer.connect())
    
    def disconnect(self):
        self._get_loop().run_until_complete(self.placer.disconnect())
    
    def place_signal(
        self,
        signal: SignalData,
        brokers: Optional[List[str]] = None
    ) -> Dict[str, OrderResult]:
        return self._get_loop().run_until_complete(
            self.placer.place_signal(signal, brokers)
        )
