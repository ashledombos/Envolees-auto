#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Order cleanup service
Cancels expired pending orders based on TradingView-aligned candle counting
Particularly important for TradeLocker which doesn't support native order expiration
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple

from brokers import (
    create_all_brokers, BaseBroker, PendingOrder, OrderResult
)
from utils.notifications import get_notification_service
from config import get_config, AppConfig


# Constants for candle calculation
CANDLE_4H_MINUTES = 4 * 60  # 240 minutes
CANDLES_EPOCH = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class CandleCalculator:
    """
    Calculate candle indices and closed candles for timeout management.
    Aligned with TradingView candle calculation.
    """
    
    # Session models
    SESSION_24X7 = "24x7"  # Crypto - always open
    SESSION_24X5 = "24x5"  # Forex, indices - closed weekends
    SESSION_RTH = "RTH"    # US stocks - regular trading hours only
    
    @staticmethod
    def get_candle_params(symbol: str, config: AppConfig) -> Tuple[int, str]:
        """
        Get candle parameters (phase and session model) for a symbol.
        
        Returns:
            Tuple of (phase_minutes, session_model)
        """
        instrument_config = config.get_instrument_config(symbol)
        
        if instrument_config:
            return (
                instrument_config.candle_phase_minutes,
                instrument_config.session_model
            )
        
        # Auto-detect from symbol name
        symbol_upper = symbol.upper()
        
        # Crypto (24/7, phase 0)
        crypto_patterns = ["BTC", "ETH", "SOL", "BNB", "LTC", "XRP", "ADA", "DOGE"]
        if any(crypto in symbol_upper for crypto in crypto_patterns):
            return (0, CandleCalculator.SESSION_24X7)
        
        # US Stocks (RTH, phase 150)
        stock_patterns = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "JPM", "V."]
        if any(stock in symbol_upper for stock in stock_patterns):
            return (150, CandleCalculator.SESSION_RTH)
        
        # Default: Forex/Metals/Indices (24x5, phase -120)
        return (-120, CandleCalculator.SESSION_24X5)
    
    @staticmethod
    def is_market_open(dt_utc: datetime, session_model: str) -> bool:
        """
        Check if market is open at a given time.
        Aligned with TradingView.
        """
        if session_model == CandleCalculator.SESSION_24X7:
            return True
        
        day_of_week = dt_utc.weekday()  # 0=Monday, 6=Sunday
        hour_utc = dt_utc.hour
        
        if session_model == CandleCalculator.SESSION_24X5:
            # Friday after 22h UTC → closed
            if day_of_week == 4 and hour_utc >= 22:
                return False
            # Saturday → closed
            if day_of_week == 5:
                return False
            # Sunday before 22h UTC → closed
            if day_of_week == 6 and hour_utc < 22:
                return False
            return True
        
        if session_model == CandleCalculator.SESSION_RTH:
            # Weekend closed
            if day_of_week >= 5:
                return False
            # RTH: 14:30-21:00 UTC (simplified check)
            minute_utc = dt_utc.minute
            time_minutes = hour_utc * 60 + minute_utc
            return 870 <= time_minutes <= 1260  # 14:30 to 21:00
        
        return True
    
    @staticmethod
    def candle_index(dt_utc: datetime, phase_minutes: int) -> int:
        """
        Calculate candle index for a datetime.
        Reproduces TradingView logic.
        """
        dt_naive = dt_utc.replace(tzinfo=None) if dt_utc.tzinfo else dt_utc
        epoch_naive = CANDLES_EPOCH.replace(tzinfo=None)
        
        total_minutes = int((dt_naive - epoch_naive).total_seconds() // 60)
        shifted = total_minutes - phase_minutes
        
        return shifted // CANDLE_4H_MINUTES
    
    @staticmethod
    def count_closed_candles(
        created_time: datetime,
        now_time: datetime,
        symbol: str,
        config: AppConfig
    ) -> int:
        """
        Count closed 4H candles between creation time and now.
        Aligned with TradingView: bars_elapsed = bar_index - confirmation_bar
        """
        phase, session_model = CandleCalculator.get_candle_params(symbol, config)
        
        # Ensure UTC
        if created_time.tzinfo is None:
            created_time = created_time.replace(tzinfo=timezone.utc)
        if now_time.tzinfo is None:
            now_time = now_time.replace(tzinfo=timezone.utc)
        
        created_idx = CandleCalculator.candle_index(created_time, phase)
        now_idx = CandleCalculator.candle_index(now_time, phase)
        
        # For 24x7 (crypto): simple count
        if session_model == CandleCalculator.SESSION_24X7:
            return max(0, now_idx - created_idx)
        
        # For 24x5 and RTH: count only valid candles
        closed_count = 0
        current_idx = created_idx
        
        while current_idx < now_idx:
            # Calculate candle start time
            candle_start_minutes = (current_idx * CANDLE_4H_MINUTES) + phase
            candle_start = CANDLES_EPOCH.replace(tzinfo=None) + timedelta(minutes=candle_start_minutes)
            candle_start = candle_start.replace(tzinfo=timezone.utc)
            
            # Check if market was open
            if CandleCalculator.is_market_open(candle_start, session_model):
                closed_count += 1
            
            current_idx += 1
            
            # Safety limit
            if current_idx > created_idx + 1000:
                break
        
        return closed_count
    
    @staticmethod
    def calculate_timeout_datetime(
        created_time: datetime,
        timeout_candles: int,
        symbol: str,
        config: AppConfig
    ) -> datetime:
        """
        Calculate when an order will timeout.
        """
        phase, session_model = CandleCalculator.get_candle_params(symbol, config)
        
        if created_time.tzinfo is None:
            created_time = created_time.replace(tzinfo=timezone.utc)
        
        created_idx = CandleCalculator.candle_index(created_time, phase)
        
        # For 24x7: simple calculation
        if session_model == CandleCalculator.SESSION_24X7:
            target_idx = created_idx + timeout_candles
            target_minutes = (target_idx * CANDLE_4H_MINUTES) + phase
            target = CANDLES_EPOCH.replace(tzinfo=None) + timedelta(minutes=target_minutes)
            return target.replace(tzinfo=timezone.utc)
        
        # For 24x5/RTH: advance counting valid candles
        current_idx = created_idx
        candles_counted = 0
        
        while candles_counted < timeout_candles:
            candle_start_minutes = (current_idx * CANDLE_4H_MINUTES) + phase
            candle_start = CANDLES_EPOCH.replace(tzinfo=None) + timedelta(minutes=candle_start_minutes)
            candle_start = candle_start.replace(tzinfo=timezone.utc)
            
            if CandleCalculator.is_market_open(candle_start, session_model):
                candles_counted += 1
            
            current_idx += 1
            
            # Safety limit
            if current_idx > created_idx + 1000:
                break
        
        final_minutes = (current_idx * CANDLE_4H_MINUTES) + phase
        final = CANDLES_EPOCH.replace(tzinfo=None) + timedelta(minutes=final_minutes)
        return final.replace(tzinfo=timezone.utc)


class OrderCleaner:
    """
    Service for cleaning up expired pending orders.
    Runs periodically to cancel orders that have exceeded their timeout.
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
            print("[OrderCleaner] No brokers configured")
            return False
        
        success = True
        for broker_id, broker in self.brokers.items():
            try:
                if await broker.connect():
                    print(f"[OrderCleaner] ✅ Connected to {broker.name}")
                else:
                    print(f"[OrderCleaner] ❌ Failed to connect to {broker.name}")
                    success = False
            except Exception as e:
                print(f"[OrderCleaner] ❌ Error connecting to {broker.name}: {e}")
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
    
    def check_order_expired(
        self,
        order: PendingOrder,
        now: Optional[datetime] = None
    ) -> Tuple[bool, int, int]:
        """
        Check if an order is expired.
        
        Returns:
            Tuple of (is_expired, closed_candles, timeout_candles)
        """
        if now is None:
            now = datetime.now(timezone.utc)
        
        if order.created_time is None:
            # Can't determine, assume not expired
            return (False, 0, self.config.general.order_timeout_candles)
        
        timeout_candles = self.config.general.order_timeout_candles
        
        closed_candles = CandleCalculator.count_closed_candles(
            order.created_time,
            now,
            order.symbol,
            self.config
        )
        
        is_expired = closed_candles >= timeout_candles
        
        return (is_expired, closed_candles, timeout_candles)
    
    async def cleanup_broker(self, broker_id: str) -> Dict[str, any]:
        """
        Clean up expired orders for a single broker.
        
        Returns:
            Dict with cleanup statistics
        """
        if broker_id not in self.brokers:
            return {"error": f"Broker {broker_id} not found"}
        
        broker = self.brokers[broker_id]
        notification_service = get_notification_service()
        
        stats = {
            "broker": broker.name,
            "orders_checked": 0,
            "orders_expired": 0,
            "orders_cancelled": 0,
            "errors": []
        }
        
        try:
            orders = await broker.get_pending_orders()
            stats["orders_checked"] = len(orders)
            
            if not orders:
                print(f"[OrderCleaner] {broker.name}: No pending orders")
                return stats
            
            now = datetime.now(timezone.utc)
            
            for order in orders:
                is_expired, closed, timeout = self.check_order_expired(order, now)
                
                # Calculate timeout time for display
                if order.created_time:
                    timeout_dt = CandleCalculator.calculate_timeout_datetime(
                        order.created_time,
                        timeout,
                        order.symbol,
                        self.config
                    )
                    timeout_str = timeout_dt.strftime("%d/%m %H:%M UTC")
                else:
                    timeout_str = "N/A"
                
                print(f"   📊 {order.symbol:<15} | ID: {order.order_id[:16]}... | "
                      f"Candles: {closed}/{timeout} | Timeout: {timeout_str}")
                
                if is_expired:
                    stats["orders_expired"] += 1
                    print(f"   ⏰ EXPIRED! ({closed} candles >= {timeout}) Cancelling...")
                    
                    result = await broker.cancel_order(order.order_id)
                    
                    if result.success:
                        stats["orders_cancelled"] += 1
                        print(f"   ✅ Cancelled")
                        
                        # Send notification
                        notification_service.notify_order_expired(
                            broker=broker.name,
                            symbol=order.symbol,
                            order_id=order.order_id,
                            reason=f"{closed} candles closed"
                        )
                    else:
                        stats["errors"].append({
                            "order_id": order.order_id,
                            "error": result.message
                        })
                        print(f"   ❌ Cancel failed: {result.message}")
            
            return stats
            
        except Exception as e:
            stats["errors"].append({"error": str(e)})
            print(f"[OrderCleaner] Error cleaning {broker.name}: {e}")
            return stats
    
    async def cleanup_all(self) -> Dict[str, Dict]:
        """
        Clean up expired orders across all brokers.
        
        Returns:
            Dict of broker_id -> cleanup stats
        """
        if not self._connected:
            await self.connect()
        
        results = {}
        
        for broker_id in self.brokers:
            print(f"\n--- {self.brokers[broker_id].name} ---")
            results[broker_id] = await self.cleanup_broker(broker_id)
        
        # Summary
        total_cancelled = sum(r.get("orders_cancelled", 0) for r in results.values())
        total_expired = sum(r.get("orders_expired", 0) for r in results.values())
        
        if total_cancelled > 0:
            print(f"\n🎯 Total: {total_cancelled}/{total_expired} expired orders cancelled")
        else:
            print("\n✅ No expired orders")
        
        return results


# Synchronous wrapper for CLI
class OrderCleanerSync:
    """Synchronous wrapper for OrderCleaner"""
    
    def __init__(self, config: Optional[AppConfig] = None):
        self.cleaner = OrderCleaner(config)
        self._loop = None
    
    def _get_loop(self):
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop
    
    def connect(self) -> bool:
        return self._get_loop().run_until_complete(self.cleaner.connect())
    
    def disconnect(self):
        self._get_loop().run_until_complete(self.cleaner.disconnect())
    
    def cleanup_all(self) -> Dict[str, Dict]:
        return self._get_loop().run_until_complete(self.cleaner.cleanup_all())
    
    def cleanup_broker(self, broker_id: str) -> Dict[str, any]:
        return self._get_loop().run_until_complete(self.cleaner.cleanup_broker(broker_id))
