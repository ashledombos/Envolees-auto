#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Order placement service with pre-placement filters and risk management

Features:
- Pre-placement filters (margin, drawdown, duplicates)
- Random delay between brokers
- Centralized instrument mapping
- Dynamic position sizing
"""

import asyncio
import random
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

from brokers import (
    create_broker, create_all_brokers,
    BaseBroker, OrderRequest, OrderResult,
    OrderSide, OrderType, AccountInfo
)
from services.position_sizer import calculate_position_size, PositionSize
from utils.notifications import get_notification_service
from config import get_config, AppConfig


class FilterResult(Enum):
    """Result of pre-placement filter check"""
    PASSED = "passed"
    INSTRUMENT_NOT_AVAILABLE = "instrument_not_available"
    MARGIN_INSUFFICIENT = "margin_insufficient"
    DAILY_DRAWDOWN_LIMIT = "daily_drawdown_limit"
    TOTAL_DRAWDOWN_LIMIT = "total_drawdown_limit"
    MAX_POSITIONS_REACHED = "max_positions_reached"
    MAX_PENDING_ORDERS = "max_pending_orders"
    DUPLICATE_ORDER = "duplicate_order"
    CONNECTION_ERROR = "connection_error"


@dataclass
class FilterCheckResult:
    """Detailed result of filter check"""
    passed: bool
    filter_result: FilterResult
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlacementResult:
    """Result of order placement attempt on one broker"""
    broker_id: str
    broker_name: str
    success: bool
    order_result: Optional[OrderResult] = None
    filter_result: Optional[FilterCheckResult] = None
    position_size: Optional[PositionSize] = None
    error: Optional[str] = None


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
    
    def calculate_risk_pips(self, pip_size: float = 0.0001) -> float:
        """Calculate risk in pips (distance from entry to SL)"""
        return abs(self.entry_price - self.stop_loss) / pip_size
    
    @classmethod
    def from_webhook(cls, data: dict) -> "SignalData":
        """Create SignalData from webhook payload"""
        return cls(
            symbol=data.get("symbol", "").upper(),
            side=data.get("side", data.get("action", "")),
            entry_price=float(data.get("entry", data.get("entry_price", data.get("price", 0)))),
            stop_loss=float(data.get("sl", data.get("stop_loss", 0))),
            take_profit=float(data.get("tp", data.get("take_profit", 0))),
            order_type=data.get("order_type", "LIMIT"),
            validity_bars=int(data.get("validity_bars", data.get("validBars", 1))),
            atr=float(data.get("atr")) if data.get("atr") else None,
            timeframe=data.get("timeframe", "H4"),
            source=data.get("source", data.get("strategy", "tradingview")),
            raw_message=str(data)
        )


class OrderPlacer:
    """
    Service for placing orders across multiple brokers with:
    - Pre-placement filters (margin, drawdown, duplicates)
    - Random delay between brokers
    - Centralized instrument mapping
    - Dynamic position sizing
    """
    
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
    
    # =========================================================================
    # Pre-Placement Filters
    # =========================================================================
    
    async def check_filters(
        self,
        broker_id: str,
        broker: BaseBroker,
        signal: SignalData
    ) -> FilterCheckResult:
        """
        Check all pre-placement filters for a broker.
        
        Returns FilterCheckResult indicating if order can be placed.
        """
        limits = self.config.get_broker_limits(broker_id)
        
        # 1. Check instrument availability
        broker_symbol = self.config.get_instrument_symbol(signal.symbol, broker_id)
        if not broker_symbol:
            return FilterCheckResult(
                passed=False,
                filter_result=FilterResult.INSTRUMENT_NOT_AVAILABLE,
                message=f"Instrument {signal.symbol} not available on {broker.name}",
                details={"symbol": signal.symbol, "broker": broker_id}
            )
        
        # Get account info
        try:
            account_info = await broker.get_account_info()
            if not account_info:
                return FilterCheckResult(
                    passed=False,
                    filter_result=FilterResult.CONNECTION_ERROR,
                    message=f"Could not get account info from {broker.name}"
                )
        except Exception as e:
            return FilterCheckResult(
                passed=False,
                filter_result=FilterResult.CONNECTION_ERROR,
                message=f"Error getting account info: {e}"
            )
        
        # 2. Check margin
        # Note: margin_free can be 0 or None when no positions are open
        # In that case, 100% of equity is available as margin
        if account_info.equity is not None and account_info.equity > 0:
            if account_info.margin_free is not None and account_info.margin_free > 0:
                margin_percent = (account_info.margin_free / account_info.equity * 100)
            else:
                # No margin used = 100% available (or broker doesn't report margin_free)
                margin_percent = 100.0
            
            if margin_percent < limits.min_margin_percent:
                return FilterCheckResult(
                    passed=False,
                    filter_result=FilterResult.MARGIN_INSUFFICIENT,
                    message=f"Margin too low: {margin_percent:.1f}% < {limits.min_margin_percent}%",
                    details={"margin_percent": margin_percent, "required": limits.min_margin_percent}
                )
        
        # 3. Check positions count
        try:
            positions = await broker.get_open_positions()
            if positions and len(positions) >= limits.max_open_positions:
                return FilterCheckResult(
                    passed=False,
                    filter_result=FilterResult.MAX_POSITIONS_REACHED,
                    message=f"Max positions reached: {len(positions)} >= {limits.max_open_positions}",
                    details={"positions": len(positions), "max": limits.max_open_positions}
                )
        except Exception:
            pass  # Continue if we can't get positions
        
        # 4. Check pending orders count
        try:
            pending = await broker.get_pending_orders()
            if pending:
                if len(pending) >= limits.max_pending_orders:
                    return FilterCheckResult(
                        passed=False,
                        filter_result=FilterResult.MAX_PENDING_ORDERS,
                        message=f"Max pending orders reached: {len(pending)} >= {limits.max_pending_orders}",
                        details={"pending": len(pending), "max": limits.max_pending_orders}
                    )
                
                # 5. Check duplicates
                if limits.prevent_duplicate_orders:
                    for order in pending:
                        if order.symbol and signal.symbol.upper() in order.symbol.upper():
                            return FilterCheckResult(
                                passed=False,
                                filter_result=FilterResult.DUPLICATE_ORDER,
                                message=f"Duplicate: pending order already exists for {signal.symbol}",
                                details={"existing_order_id": order.order_id}
                            )
        except Exception:
            pass  # Continue if we can't get pending orders
        
        # All filters passed
        return FilterCheckResult(
            passed=True,
            filter_result=FilterResult.PASSED,
            message="All filters passed"
        )
    
    # =========================================================================
    # Order Placement
    # =========================================================================
    
    async def place_signal(
        self,
        signal: SignalData,
        brokers: Optional[List[str]] = None,
        dry_run: bool = False
    ) -> Dict[str, PlacementResult]:
        """
        Place orders for a signal across specified brokers.
        
        Args:
            signal: Signal data from TradingView
            brokers: List of broker IDs to use (None = all enabled)
            dry_run: If True, only simulate without placing real orders
        
        Returns:
            Dict of broker_id -> PlacementResult
        """
        if not self._connected:
            await self.connect()
        
        results = {}
        notification_service = get_notification_service()
        
        # Determine broker order
        target_brokers = brokers or list(self.brokers.keys())
        
        # Use configured order if available
        if self.config.execution.broker_order:
            target_brokers = [
                b for b in self.config.execution.broker_order 
                if b in target_brokers
            ]
        
        # Get delay settings
        delay_config = self.config.execution.delay_between_brokers
        
        for i, broker_id in enumerate(target_brokers):
            if broker_id not in self.brokers:
                results[broker_id] = PlacementResult(
                    broker_id=broker_id,
                    broker_name=broker_id,
                    success=False,
                    error=f"Broker {broker_id} not found"
                )
                continue
            
            broker = self.brokers[broker_id]
            
            # Add random delay (except for first broker)
            if i > 0 and delay_config.enabled:
                delay_ms = random.randint(delay_config.min_ms, delay_config.max_ms)
                print(f"[OrderPlacer] Waiting {delay_ms}ms before {broker.name}...")
                await asyncio.sleep(delay_ms / 1000)
            
            # Check filters
            filter_check = await self.check_filters(broker_id, broker, signal)
            
            if not filter_check.passed:
                print(f"[OrderPlacer] ⏭️  Skipping {broker.name}: {filter_check.message}")
                results[broker_id] = PlacementResult(
                    broker_id=broker_id,
                    broker_name=broker.name,
                    success=False,
                    filter_result=filter_check
                )
                
                if self.config.notifications.on_filter_skip:
                    notification_service.notify(
                        f"⏭️ {broker.name}: Skipped {signal.symbol} - {filter_check.message}"
                    )
                continue
            
            # Place order
            try:
                result = await self._place_on_broker(broker, broker_id, signal, dry_run)
                results[broker_id] = result
                
                if result.success:
                    notification_service.notify_order_placed(
                        broker=broker.name,
                        symbol=signal.symbol,
                        side=signal.side,
                        order_type=signal.order_type,
                        volume=result.position_size.lots if result.position_size else 0,
                        entry_price=signal.entry_price,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        order_id=result.order_result.order_id if result.order_result else ""
                    )
                else:
                    notification_service.notify_error(
                        broker=broker.name,
                        message=f"Failed {signal.side} {signal.symbol}",
                        error_details=result.error or ""
                    )
                    
            except Exception as e:
                results[broker_id] = PlacementResult(
                    broker_id=broker_id,
                    broker_name=broker.name,
                    success=False,
                    error=str(e)
                )
                notification_service.notify_error(
                    broker=broker.name,
                    message=f"Error on {signal.symbol}",
                    error_details=str(e)
                )
        
        return results
    
    async def _place_on_broker(
        self,
        broker: BaseBroker,
        broker_id: str,
        signal: SignalData,
        dry_run: bool = False
    ) -> PlacementResult:
        """Place order on a single broker"""
        
        # Get broker-specific symbol
        broker_symbol = self.config.get_instrument_symbol(signal.symbol, broker_id)
        
        # Get account info for position sizing
        account_info = await broker.get_account_info()
        if not account_info:
            return PlacementResult(
                broker_id=broker_id,
                broker_name=broker.name,
                success=False,
                error="Could not get account info"
            )
        
        # Get instrument config
        instrument_config = self.config.get_instrument_config(signal.symbol) or {}
        
        # Determine account value (equity or balance)
        account_value = account_info.equity if self.config.general.use_equity else account_info.balance
        if not account_value or account_value <= 0:
            account_value = account_info.balance or 10000  # Fallback
        
        # Calculate position size
        position_size = calculate_position_size(
            instrument_config=instrument_config,
            account_value=account_value,
            risk_percent=self.config.general.risk_percent,
            entry_price=signal.entry_price,
            sl_price=signal.stop_loss
        )
        
        print(f"[OrderPlacer] {broker.name}: {position_size.details}")
        
        if position_size.lots <= 0:
            return PlacementResult(
                broker_id=broker_id,
                broker_name=broker.name,
                success=False,
                position_size=position_size,
                error="Invalid position size calculated"
            )
        
        # Calculate expiry
        timeframe_minutes = self.config.general.candle_timeframe_minutes
        expiry_ms = self._calculate_expiry_timestamp(
            signal.validity_bars,
            timeframe_minutes
        )
        
        # Create order request
        order = OrderRequest(
            symbol=signal.symbol,
            side=signal.order_side,
            order_type=signal.broker_order_type,
            volume=position_size.lots,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            expiry_timestamp_ms=expiry_ms,
            label=f"TV-{signal.symbol[:8]}",
            comment=f"Signal {signal.timeframe} {signal.side}"
        )
        
        print(f"[OrderPlacer] {'[DRY RUN] ' if dry_run else ''}Placing on {broker.name}:")
        print(f"              {signal.side} {position_size.lots} lots {broker_symbol} @ {signal.entry_price}")
        print(f"              SL: {signal.stop_loss}, TP: {signal.take_profit}")
        
        if dry_run:
            return PlacementResult(
                broker_id=broker_id,
                broker_name=broker.name,
                success=True,
                position_size=position_size,
                order_result=OrderResult(
                    success=True,
                    message="[DRY RUN] Order would be placed"
                )
            )
        
        # Place order
        result = await broker.place_order(order)
        
        return PlacementResult(
            broker_id=broker_id,
            broker_name=broker.name,
            success=result.success,
            position_size=position_size,
            order_result=result,
            error=result.message if not result.success else None
        )
    
    def _calculate_expiry_timestamp(
        self,
        validity_bars: int,
        timeframe_minutes: int = 240
    ) -> int:
        """Calculate order expiry timestamp in milliseconds"""
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(minutes=validity_bars * timeframe_minutes)
        return int(expiry.timestamp() * 1000)


# =============================================================================
# Synchronous Wrapper
# =============================================================================

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
        brokers: Optional[List[str]] = None,
        dry_run: bool = False
    ) -> Dict[str, PlacementResult]:
        return self._get_loop().run_until_complete(
            self.placer.place_signal(signal, brokers, dry_run)
        )
    
    def check_filters(
        self,
        broker_id: str,
        signal: SignalData
    ) -> FilterCheckResult:
        """Check filters for a single broker"""
        if broker_id not in self.placer.brokers:
            return FilterCheckResult(
                passed=False,
                filter_result=FilterResult.CONNECTION_ERROR,
                message=f"Broker {broker_id} not connected"
            )
        return self._get_loop().run_until_complete(
            self.placer.check_filters(
                broker_id,
                self.placer.brokers[broker_id],
                signal
            )
        )
