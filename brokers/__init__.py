#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Broker module - Factory and exports
"""

from typing import Optional, Dict

from .base import (
    BaseBroker,
    OrderRequest, OrderResult,
    OrderSide, OrderType, OrderStatus,
    Position, PendingOrder,
    AccountInfo, SymbolInfo
)


def create_broker(broker_id: str, config: dict, sync: bool = False) -> Optional[BaseBroker]:
    """
    Factory function to create broker instance based on type.
    
    Args:
        broker_id: Unique identifier for this broker instance
        config: Broker configuration dict
        sync: If True, return synchronous wrapper (for CLI usage)
    
    Returns:
        Broker instance or None if type not supported
    """
    broker_type = config.get("type", "").lower()
    
    if broker_type == "ctrader":
        from .ctrader import CTraderBroker, CTraderBrokerSync
        if sync:
            return CTraderBrokerSync(broker_id, config)
        return CTraderBroker(broker_id, config)
    
    elif broker_type == "tradelocker":
        from .tradelocker import TradeLockerBroker, TradeLockerBrokerSync
        if sync:
            return TradeLockerBrokerSync(broker_id, config)
        return TradeLockerBroker(broker_id, config)
    
    else:
        print(f"Unknown broker type: {broker_type}")
        return None


def create_all_brokers(brokers_config: Dict[str, dict], enabled_only: bool = True, sync: bool = False) -> Dict[str, BaseBroker]:
    """
    Create all broker instances from config.
    
    Args:
        brokers_config: Dict of broker_id -> config
        enabled_only: Only create enabled brokers
        sync: If True, return synchronous wrappers
    
    Returns:
        Dict of broker_id -> broker instance
    """
    brokers = {}
    
    for broker_id, config in brokers_config.items():
        if enabled_only and not config.get("enabled", False):
            continue
        
        broker = create_broker(broker_id, config, sync=sync)
        if broker:
            brokers[broker_id] = broker
    
    return brokers


__all__ = [
    # Factory
    "create_broker",
    "create_all_brokers",
    
    # Base classes and types
    "BaseBroker",
    "OrderRequest", "OrderResult",
    "OrderSide", "OrderType", "OrderStatus",
    "Position", "PendingOrder",
    "AccountInfo", "SymbolInfo",
]
