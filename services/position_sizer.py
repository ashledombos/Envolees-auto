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
    
    # Default pip values for common quote currencies (approximate, conservative)
    # These are used as sanity check bounds and fallbacks
    # Based on typical exchange rates - updated periodically
    DEFAULT_PIP_VALUES = {
        "JPY": 6.5,    # ~1000/155 (USDJPY ~155)
        "CHF": 11.0,   # ~10/0.90 (USDCHF ~0.90)
        "GBP": 12.5,   # ~10/0.80 (GBPUSD ~1.25, so USDGBP ~0.80)
        "CAD": 7.2,    # ~10/1.38 (USDCAD ~1.38)
        "AUD": 6.5,    # ~10/1.55 (AUDUSD ~0.65, so USDAUD ~1.55)
        "NZD": 5.9,    # ~10/1.70 (NZDUSD ~0.59, so USDNZD ~1.70)
        "EUR": 10.8,   # ~10/0.93 (EURUSD ~1.08, so USDEUR ~0.93)
        "ZAR": 0.55,   # ~10/18 (USDZAR ~18)
        "MXN": 0.50,   # ~10/20 (USDMXN ~20)
        "CNH": 1.4,    # ~10/7.2 (USDCNH ~7.2)
        "SGD": 7.4,    # ~10/1.35 (USDSGD ~1.35)
        "NOK": 0.90,   # ~10/11 (USDNOK ~11)
        "HUF": 0.026,  # ~10/380 (USDHUF ~380)
        "CZK": 0.42,   # ~10/24 (USDCZK ~24)
    }
    
    # Maximum deviation allowed from expected pip value (safety margin)
    MAX_PIP_VALUE_DEVIATION = 0.50  # 50% - if calculated value deviates more, use default
    
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
        lot_step: float = 0.01,
        symbol: str = "UNKNOWN"
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
            symbol: Symbol name for logging
        
        Returns:
            PositionSize with calculated lots and details
        """
        # Calculate risk amount
        risk_amount = account_value * (risk_percent / 100)
        
        # Calculate SL distance in pips
        sl_distance = abs(entry_price - sl_price)
        sl_pips = sl_distance / self.pip_size
        
        # Debug logging for non-USD pairs
        if self.quote_currency and self.quote_currency != "USD":
            print(f"[PositionSizer] {symbol} DEBUG:")
            print(f"   pip_size: {self.pip_size}")
            print(f"   pip_value_per_lot (config): {self.pip_value_per_lot}")
            print(f"   quote_currency: {self.quote_currency}")
            print(f"   contract_size: {self.contract_size}")
            print(f"   entry_price: {entry_price}")
            print(f"   sl_price: {sl_price}")
            print(f"   sl_distance: {sl_distance}")
            print(f"   sl_pips: {sl_pips:.2f}")
        
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
        
        Uses a sanity check against known default values to prevent
        calculation errors that could lead to oversized positions.
        
        Cases:
        1. XXX/USD pairs: pip value = 10 USD (fixed)
        2. USD/XXX pairs: pip value = 10 / current_price
        3. XXX/YYY pairs: pip value depends on YYY/USD rate
        """
        # If static value is configured, use it (most reliable)
        if self.pip_value_per_lot is not None:
            return self.pip_value_per_lot
        
        # Get default value for this quote currency (if known)
        default_pip_value = None
        if self.quote_currency and self.quote_currency in self.DEFAULT_PIP_VALUES:
            default_pip_value = self.DEFAULT_PIP_VALUES[self.quote_currency]
            
            # Adjust for non-standard pip sizes (e.g., JPY pairs with 0.01 pip)
            # Standard forex pip = 0.0001, JPY pip = 0.01 (100x larger)
            if self.pip_size >= 0.01 and self.quote_currency == "JPY":
                # JPY pair - default is already correct
                pass
            elif self.pip_size >= 0.001 and self.quote_currency not in ["JPY"]:
                # Non-standard pip size, scale accordingly
                scale = self.pip_size / 0.0001
                default_pip_value = default_pip_value * scale
        
        # Standard forex lot = 100,000 units
        base_pip_value = self.contract_size * self.pip_size
        
        if self.quote_currency is None or self.quote_currency == "USD":
            return base_pip_value  # = 10 for standard forex
        
        # Try to calculate dynamically
        calculated_pip_value = None
        
        if quote_to_usd_rate is not None:
            # Explicit rate provided - use it
            calculated_pip_value = base_pip_value * quote_to_usd_rate
        elif current_price > 1:
            # Estimate by dividing base_pip_value by current price
            # This works for USD/XXX pairs but is WRONG for XXX/YYY crosses!
            calculated_pip_value = base_pip_value / current_price
        
        # Sanity check: compare calculated vs default
        if calculated_pip_value is not None and default_pip_value is not None:
            deviation = abs(calculated_pip_value - default_pip_value) / default_pip_value
            
            if deviation > self.MAX_PIP_VALUE_DEVIATION:
                # Calculated value deviates too much from expected
                # This likely means we're using wrong price (e.g., CHFJPY price instead of USDJPY)
                print(f"[PositionSizer] ⚠️  Pip value sanity check FAILED:")
                print(f"   Calculated: ${calculated_pip_value:.2f}")
                print(f"   Expected ({self.quote_currency}): ${default_pip_value:.2f}")
                print(f"   Deviation: {deviation*100:.1f}% > {self.MAX_PIP_VALUE_DEVIATION*100:.0f}% max")
                print(f"   → Using safe default: ${default_pip_value:.2f}")
                return default_pip_value
            else:
                # Calculated value is within acceptable range
                return calculated_pip_value
        
        # If we have a default but no calculated value, use default
        if default_pip_value is not None:
            print(f"[PositionSizer] Using default pip value for {self.quote_currency}: ${default_pip_value:.2f}")
            return default_pip_value
        
        # If we have a calculated value but no default to check against
        if calculated_pip_value is not None:
            print(f"[PositionSizer] ⚠️  No default pip value for {self.quote_currency}, using calculated: ${calculated_pip_value:.2f}")
            return calculated_pip_value
        
        # Last resort fallback
        print(f"[PositionSizer] ⚠️  Could not determine pip value, using base: ${base_pip_value:.2f}")
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
    
    # Test 4: USDZAR (ZAR quote - exotic)
    print("\n4. USDZAR - $97,000 account, 0.5% risk, ~567 pip SL")
    config = {"pip_size": 0.0001, "quote_currency": "ZAR"}
    result = calculate_position_size(
        config,
        account_value=97000,
        risk_percent=0.5,
        entry_price=16.29158,
        sl_price=16.34826  # 566.68 pips
    )
    print(f"   Result: {result.lots} lots")
    print(f"   {result.details}")
    print(f"   Expected: ~1.4 lots (risk $485 / (567 pips × $0.61/pip/lot))")
    
    # Test 5: USDMXN (MXN quote - exotic)
    print("\n5. USDMXN - $100,000 account, 0.5% risk, 500 pip SL")
    config = {"pip_size": 0.0001, "quote_currency": "MXN"}
    result = calculate_position_size(
        config,
        account_value=100000,
        risk_percent=0.5,
        entry_price=17.50,
        sl_price=17.55  # 500 pips
    )
    print(f"   Result: {result.lots} lots")
    print(f"   {result.details}")
