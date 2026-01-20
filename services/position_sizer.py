#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Position Sizing Calculator

Calculates lot sizes based on:
- Account balance/equity
- Risk percentage
- Stop loss distance
- Pip value (static or dynamic)
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class PositionSize:
    """Result of position size calculation"""
    lots: float
    risk_amount: float  # Amount risked in account currency
    pip_value: float    # Value per pip for calculated lot size
    sl_pips: float      # Stop loss in pips
    details: str        # Human-readable explanation


class PositionSizer:
    """
    Calculate position sizes based on risk management rules.
    
    Formula:
        Lot Size = (Account × Risk%) / (SL_pips × Pip_value_per_lot)
    
    For pairs where USD is not the quote currency, we need the current
    exchange rate to calculate pip value in USD.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize with configuration.
        
        Args:
            config: Instrument configuration containing:
                - pip_size: Size of one pip (e.g., 0.0001 for EURUSD)
                - pip_value_per_lot: Value in USD of 1 pip for 1 standard lot
                - contract_size: Contract size (default 100000 for forex)
                - quote_currency: Quote currency for dynamic calculation
        """
        self.pip_size = config.get("pip_size", 0.0001)
        self.pip_value_per_lot = config.get("pip_value_per_lot")  # May be None
        self.contract_size = config.get("contract_size", 100000)
        self.quote_currency = config.get("quote_currency")
    
    def calculate(
        self,
        account_value: float,
        risk_percent: float,
        entry_price: float,
        sl_price: float,
        current_price: Optional[float] = None,
        quote_to_usd_rate: Optional[float] = None,
        min_lot: float = 0.01,
        max_lot: float = 100.0,
        lot_step: float = 0.01
    ) -> PositionSize:
        """
        Calculate position size.
        
        Args:
            account_value: Account balance or equity in USD
            risk_percent: Risk percentage (e.g., 0.5 for 0.5%)
            entry_price: Entry price
            sl_price: Stop loss price
            current_price: Current market price (for dynamic pip value)
            quote_to_usd_rate: Exchange rate if quote currency is not USD
            min_lot: Minimum lot size allowed
            max_lot: Maximum lot size allowed
            lot_step: Lot size increment
        
        Returns:
            PositionSize with calculated lots and details
        """
        # Calculate risk amount
        risk_amount = account_value * (risk_percent / 100)
        
        # Calculate SL distance in pips
        sl_distance = abs(entry_price - sl_price)
        sl_pips = sl_distance / self.pip_size
        
        if sl_pips == 0:
            return PositionSize(
                lots=0,
                risk_amount=risk_amount,
                pip_value=0,
                sl_pips=0,
                details="Error: SL distance is zero"
            )
        
        # Determine pip value per lot
        pip_value_per_lot = self._get_pip_value(
            current_price or entry_price,
            quote_to_usd_rate
        )
        
        if pip_value_per_lot <= 0:
            return PositionSize(
                lots=0,
                risk_amount=risk_amount,
                pip_value=0,
                sl_pips=sl_pips,
                details="Error: Could not determine pip value"
            )
        
        # Calculate lot size
        # lots = risk_amount / (sl_pips × pip_value_per_lot)
        raw_lots = risk_amount / (sl_pips * pip_value_per_lot)
        
        # Round to lot step
        lots = round(raw_lots / lot_step) * lot_step
        
        # Apply min/max limits
        lots = max(min_lot, min(lots, max_lot))
        
        # Recalculate actual risk with rounded lots
        actual_risk = lots * sl_pips * pip_value_per_lot
        actual_pip_value = lots * pip_value_per_lot
        
        details = (
            f"Account: ${account_value:,.2f} | "
            f"Risk: {risk_percent}% = ${risk_amount:,.2f} | "
            f"SL: {sl_pips:.1f} pips | "
            f"Pip value/lot: ${pip_value_per_lot:.2f} | "
            f"Raw lots: {raw_lots:.4f} → {lots:.2f} lots | "
            f"Actual risk: ${actual_risk:,.2f}"
        )
        
        return PositionSize(
            lots=lots,
            risk_amount=actual_risk,
            pip_value=actual_pip_value,
            sl_pips=sl_pips,
            details=details
        )
    
    def _get_pip_value(
        self,
        current_price: float,
        quote_to_usd_rate: Optional[float] = None
    ) -> float:
        """
        Get pip value per standard lot in USD.
        
        Cases:
        1. XXX/USD pairs: pip value = 10 USD (fixed)
        2. USD/XXX pairs: pip value = 10 / current_price
        3. XXX/YYY pairs: pip value = 10 × (YYY/USD rate)
        
        For simplicity, if pip_value_per_lot is configured, use it.
        Otherwise, try to calculate dynamically.
        """
        # If static value is configured, use it
        if self.pip_value_per_lot is not None:
            return self.pip_value_per_lot
        
        # Standard forex lot = 100,000 units
        # 1 pip = pip_size (e.g., 0.0001)
        # Pip value = contract_size × pip_size × conversion_rate
        
        base_pip_value = self.contract_size * self.pip_size
        
        if self.quote_currency is None:
            # Assume USD is quote currency
            return base_pip_value  # = 10 for standard forex
        
        # Need to convert from quote currency to USD
        if self.quote_currency == "USD":
            return base_pip_value
        
        if quote_to_usd_rate is not None:
            # XXX/YYY pair - convert YYY to USD
            return base_pip_value * quote_to_usd_rate
        
        # If we have current price and it's a USD/XXX pair
        # (quote currency is not USD, but we can estimate)
        # This is a rough approximation
        if self.quote_currency in ["JPY", "CHF", "CAD"]:
            # For pairs like USDJPY, pip value ≈ 10 / price
            # For EURJPY, we'd need USDJPY rate, but approximate with entry
            if current_price > 10:  # Likely a JPY pair
                return base_pip_value / (current_price / 100)
            else:
                return base_pip_value / current_price
        
        # Default fallback
        return base_pip_value


def calculate_position_size(
    instrument_config: Dict[str, Any],
    account_value: float,
    risk_percent: float,
    entry_price: float,
    sl_price: float,
    **kwargs
) -> PositionSize:
    """
    Convenience function to calculate position size.
    
    Args:
        instrument_config: Instrument configuration dict
        account_value: Account balance/equity
        risk_percent: Risk percentage
        entry_price: Entry price
        sl_price: Stop loss price
        **kwargs: Additional arguments passed to calculate()
    
    Returns:
        PositionSize result
    """
    sizer = PositionSizer(instrument_config)
    return sizer.calculate(
        account_value=account_value,
        risk_percent=risk_percent,
        entry_price=entry_price,
        sl_price=sl_price,
        **kwargs
    )


# =============================================================================
# Testing
# =============================================================================

if __name__ == "__main__":
    # Test cases
    print("=" * 60)
    print("Position Sizing Tests")
    print("=" * 60)
    
    # Test 1: EURUSD (USD quote)
    print("\n1. EURUSD - $100,000 account, 0.5% risk, 30 pip SL")
    config = {"pip_size": 0.0001, "pip_value_per_lot": 10}
    result = calculate_position_size(
        config,
        account_value=100000,
        risk_percent=0.5,
        entry_price=1.0850,
        sl_price=1.0820
    )
    print(f"   Result: {result.lots} lots")
    print(f"   {result.details}")
    
    # Test 2: USDJPY (JPY quote)
    print("\n2. USDJPY - $50,000 account, 1% risk, 50 pip SL")
    config = {"pip_size": 0.01, "quote_currency": "JPY"}
    result = calculate_position_size(
        config,
        account_value=50000,
        risk_percent=1.0,
        entry_price=150.50,
        sl_price=151.00
    )
    print(f"   Result: {result.lots} lots")
    print(f"   {result.details}")
    
    # Test 3: XAUUSD (Gold)
    print("\n3. XAUUSD - $100,000 account, 0.5% risk, $10 SL")
    config = {"pip_size": 0.01, "pip_value_per_lot": 1, "contract_size": 100}
    result = calculate_position_size(
        config,
        account_value=100000,
        risk_percent=0.5,
        entry_price=2650.00,
        sl_price=2640.00
    )
    print(f"   Result: {result.lots} lots")
    print(f"   {result.details}")
