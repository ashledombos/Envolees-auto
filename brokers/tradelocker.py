#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeLocker broker implementation using official tradelocker library
https://pypi.org/project/tradelocker/
"""

import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from .base import (
    BaseBroker, OrderRequest, OrderResult, OrderSide, OrderType, OrderStatus,
    Position, PendingOrder, AccountInfo, SymbolInfo
)

# Suppress tradelocker debug output
os.environ.setdefault('TRADELOCKER_LOG_LEVEL', 'WARNING')

try:
    from tradelocker import TLAPI
    TRADELOCKER_AVAILABLE = True
except ImportError:
    TRADELOCKER_AVAILABLE = False
    print("⚠️  tradelocker library not installed. Install with: pip install tradelocker")


class TradeLockerBroker(BaseBroker):
    """
    TradeLocker broker implementation using official library.
    
    Config example:
        gft_compte1:
            enabled: true
            type: tradelocker
            name: "GFT Funded #1"
            base_url: "https://bsb.tradelocker.com"
            email: "your@email.com"
            password: "your_password"
            server: "GFTTL"
            account_id: 1711519  # Optional, uses first if not set
    """
    
    def __init__(self, broker_id: str, config: dict):
        super().__init__(broker_id, config)
        
        if not TRADELOCKER_AVAILABLE:
            raise ImportError("tradelocker library not installed. Run: pip install tradelocker")
        
        self.email = config.get("email", "")
        self.password = config.get("password", "")
        self.server = config.get("server", "GFTTL")
        self.base_url = config.get("base_url", "https://demo.tradelocker.com")
        
        # Account ID from config (optional)
        self._configured_account_id = config.get("account_id")
        
        # TLAPI instance
        self._api: Optional[TLAPI] = None
        self._account_id: Optional[int] = None
        self._acc_num: Optional[int] = None
        
        # Instrument cache
        self._instruments_df = None
        self._instruments_map: Dict[str, int] = {}  # name -> tradableInstrumentId
        self._instruments_reverse_map: Dict[int, str] = {}  # tradableInstrumentId -> name
    
    async def connect(self) -> bool:
        """Connect to TradeLocker using official library"""
        try:
            # Initialize TLAPI
            self._api = TLAPI(
                environment=self.base_url,
                username=self.email,
                password=self.password,
                server=self.server,
                log_level='warning'  # Reduce noise
            )
            
            print(f"[TradeLocker] ✅ Authenticated to {self.base_url}")
            
            # Get accounts
            accounts_df = self._api.get_all_accounts()
            
            if accounts_df is None or accounts_df.empty:
                print("[TradeLocker] ❌ No accounts found")
                return False
            
            # Display accounts
            print(f"[TradeLocker] Found {len(accounts_df)} account(s):")
            for _, acc in accounts_df.iterrows():
                status = "✅" if acc.get('status') == 'ACTIVE' else "⚪"
                print(f"   {status} ID: {acc['id']} | accNum: {acc['accNum']} | {acc['name']}")
            
            # Select account
            if self._configured_account_id:
                # Use configured account
                matching = accounts_df[accounts_df['id'] == self._configured_account_id]
                if not matching.empty:
                    selected = matching.iloc[0]
                else:
                    print(f"[TradeLocker] ⚠️  Configured account {self._configured_account_id} not found, using first")
                    selected = accounts_df.iloc[0]
            else:
                # Use first active account
                active = accounts_df[accounts_df['status'] == 'ACTIVE']
                selected = active.iloc[0] if not active.empty else accounts_df.iloc[0]
            
            self._account_id = int(selected['id'])
            self._acc_num = int(selected['accNum'])
            
            print(f"[TradeLocker] ✅ Using account: {self._acc_num} (ID: {self._account_id})")
            
            # Reinitialize API with specific account
            self._api = TLAPI(
                environment=self.base_url,
                username=self.email,
                password=self.password,
                server=self.server,
                acc_num=self._acc_num,
                log_level='warning'
            )
            
            # Load instruments
            await self._load_instruments()
            
            self._connected = True
            return True
            
        except Exception as e:
            print(f"[TradeLocker] ❌ Connection error: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from TradeLocker"""
        self._api = None
        self._connected = False
    
    async def _load_instruments(self):
        """Load and cache instruments"""
        try:
            self._instruments_df = self._api.get_all_instruments()
            
            if self._instruments_df is not None and not self._instruments_df.empty:
                for _, inst in self._instruments_df.iterrows():
                    inst_id = int(inst['tradableInstrumentId'])
                    inst_name = inst['name']
                    self._instruments_map[inst_name] = inst_id
                    self._instruments_reverse_map[inst_id] = inst_name
                
                print(f"[TradeLocker] Loaded {len(self._instruments_map)} instruments")
            else:
                print("[TradeLocker] ⚠️  No instruments loaded")
                
        except Exception as e:
            print(f"[TradeLocker] Error loading instruments: {e}")
    
    def _get_instrument_id(self, symbol: str) -> Optional[int]:
        """Get tradableInstrumentId from symbol name"""
        # Check direct mapping in config
        mapping = self.config.get("instruments_mapping", {})
        if symbol in mapping:
            broker_symbol = mapping[symbol]
            if broker_symbol in self._instruments_map:
                return self._instruments_map[broker_symbol]
        
        # Direct lookup
        if symbol in self._instruments_map:
            return self._instruments_map[symbol]
        
        # Try with .X suffix (GFT convention)
        symbol_x = f"{symbol}.X"
        if symbol_x in self._instruments_map:
            return self._instruments_map[symbol_x]
        
        return None
    
    def map_symbol(self, symbol: str) -> Optional[str]:
        """Map TradingView symbol to TradeLocker symbol"""
        # Check config mapping first
        mapping = self.config.get("instruments_mapping", {})
        if symbol in mapping:
            return mapping[symbol]
        
        # Direct match
        if symbol in self._instruments_map:
            return symbol
        
        # Try with .X suffix
        symbol_x = f"{symbol}.X"
        if symbol_x in self._instruments_map:
            return symbol_x
        
        return None
    
    async def get_account_info(self) -> Optional[AccountInfo]:
        """Get account information"""
        if not self._api:
            return None
        
        try:
            accounts_df = self._api.get_all_accounts()
            
            if accounts_df is None or accounts_df.empty:
                return None
            
            # Find our account
            acc = accounts_df[accounts_df['id'] == self._account_id]
            if acc.empty:
                acc = accounts_df.iloc[[0]]
            
            acc = acc.iloc[0]
            
            balance = float(acc.get('accountBalance', 0))
            currency = acc.get('currency', 'USD')
            
            # Get more details from account state if available
            try:
                # The library might have additional account info methods
                # For now, use what we have from accounts
                equity = balance  # Will be same if no positions
                margin_free = balance  # Simplified
            except:
                equity = balance
                margin_free = balance
            
            return AccountInfo(
                account_id=str(self._account_id),
                broker_name=self.name,
                balance=balance,
                equity=equity,
                margin_free=margin_free,
                margin_used=0,
                currency=currency,
                leverage=100,  # Default for prop firms
                is_demo=self.config.get("is_demo", True)
            )
            
        except Exception as e:
            print(f"[TradeLocker] Error getting account info: {e}")
            return None
    
    async def get_symbols(self) -> List[str]:
        """Get list of available symbols"""
        return list(self._instruments_map.keys())
    
    async def get_symbol_info(self, symbol: str) -> Optional[SymbolInfo]:
        """Get symbol information"""
        if self._instruments_df is None or self._instruments_df.empty:
            return None
        
        broker_symbol = self.map_symbol(symbol)
        if not broker_symbol:
            return None
        
        try:
            inst = self._instruments_df[self._instruments_df['name'] == broker_symbol]
            if inst.empty:
                return None
            
            inst = inst.iloc[0]
            
            return SymbolInfo(
                symbol=broker_symbol,
                description=inst.get('description', ''),
                pip_size=float(inst.get('pipSize', 0.0001)),
                pip_value=float(inst.get('pipValue', 10)),
                lot_size=float(inst.get('contractSize', 100000)),
                min_lot=float(inst.get('minOrderSize', 0.01)),
                max_lot=float(inst.get('maxOrderSize', 100)),
                lot_step=float(inst.get('orderSizeStep', 0.01))
            )
        except Exception as e:
            print(f"[TradeLocker] Error getting symbol info: {e}")
            return None
    
    async def place_order(self, order: OrderRequest) -> OrderResult:
        """Place an order"""
        if not self._api:
            return OrderResult(success=False, message="Not connected")
        
        # Get instrument ID
        broker_symbol = self.map_symbol(order.symbol)
        inst_id = self._get_instrument_id(order.symbol)
        
        if not inst_id:
            return OrderResult(
                success=False,
                message=f"Symbol {order.symbol} not found (tried {broker_symbol})"
            )
        
        try:
            # Determine order type for TradeLocker
            # TradeLocker uses: 'market', 'limit', 'stop'
            if order.order_type == OrderType.MARKET:
                tl_type = 'market'
            elif order.order_type == OrderType.LIMIT:
                tl_type = 'limit'
            elif order.order_type == OrderType.STOP:
                tl_type = 'stop'
            else:
                tl_type = 'limit'
            
            # Side
            tl_side = 'buy' if order.side == OrderSide.BUY else 'sell'
            
            # Create order using official library
            order_params = {
                'instrument_id': inst_id,
                'quantity': order.volume,
                'side': tl_side,
                'type_': tl_type,
            }
            
            # Add price and validity for non-market orders
            if tl_type != 'market':
                order_params['price'] = order.entry_price
                order_params['validity'] = 'GTC'  # Good Till Cancelled
            
            # Add SL/TP with absolute price type
            if order.stop_loss:
                order_params['stop_loss'] = order.stop_loss
                order_params['stop_loss_type'] = 'absolute'
            if order.take_profit:
                order_params['take_profit'] = order.take_profit
                order_params['take_profit_type'] = 'absolute'
            
            result = self._api.create_order(**order_params)
            
            if result is not None:
                # Extract order ID from result
                # The library may return an int (order ID) or a dict
                if isinstance(result, int):
                    order_id = str(result)
                elif isinstance(result, dict):
                    order_id = str(result.get('orderId', result.get('id', 'unknown')))
                else:
                    order_id = str(result)
                
                print(f"[TradeLocker] ✅ Order placed: {order_id}")
                
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    message="Order placed successfully",
                    broker_response=result
                )
            else:
                return OrderResult(
                    success=False,
                    message="Order creation returned None"
                )
                
        except Exception as e:
            error_msg = str(e)
            print(f"[TradeLocker] ❌ Order error: {error_msg}")
            return OrderResult(
                success=False,
                message=error_msg
            )
    
    async def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel a pending order"""
        if not self._api:
            return OrderResult(success=False, message="Not connected")
        
        try:
            result = self._api.delete_order(int(order_id))
            
            if result:
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    message="Order cancelled"
                )
            else:
                return OrderResult(
                    success=False,
                    order_id=order_id,
                    message="Failed to cancel order"
                )
                
        except Exception as e:
            return OrderResult(
                success=False,
                order_id=order_id,
                message=str(e)
            )
    
    async def get_pending_orders(self) -> List[PendingOrder]:
        """Get list of pending orders"""
        if not self._api:
            return []
        
        try:
            orders_df = self._api.get_all_orders()
            
            if orders_df is None or orders_df.empty:
                return []
            
            pending = []
            for _, order in orders_df.iterrows():
                status = order.get('status', '').upper()
                if status in ['PENDING', 'NEW', 'WORKING']:
                    # Get symbol name from instrument ID
                    inst_id = order.get('tradableInstrumentId')
                    symbol = self._instruments_reverse_map.get(inst_id, str(inst_id))
                    
                    pending.append(PendingOrder(
                        order_id=str(order.get('id', '')),
                        symbol=symbol,
                        side=OrderSide.BUY if order.get('side', '').lower() == 'buy' else OrderSide.SELL,
                        order_type=OrderType.LIMIT,  # Simplified
                        volume=float(order.get('qty', 0)),
                        entry_price=float(order.get('price', 0)),
                        stop_loss=float(order.get('stopLoss', 0)) if order.get('stopLoss') else None,
                        take_profit=float(order.get('takeProfit', 0)) if order.get('takeProfit') else None,
                        status=OrderStatus.PENDING,
                        created_at=datetime.now(timezone.utc)
                    ))
            
            return pending
            
        except Exception as e:
            print(f"[TradeLocker] Error getting orders: {e}")
            return []
    
    async def get_positions(self) -> List[Position]:
        """Get all open positions"""
        if not self._api:
            return []
        
        try:
            positions_df = self._api.get_all_positions()
            
            if positions_df is None or positions_df.empty:
                return []
            
            positions = []
            for _, pos in positions_df.iterrows():
                inst_id = pos.get('tradableInstrumentId')
                symbol = self._instruments_reverse_map.get(inst_id, str(inst_id))
                
                positions.append(Position(
                    position_id=str(pos.get('id', '')),
                    symbol=symbol,
                    side=OrderSide.BUY if pos.get('side', '').lower() == 'buy' else OrderSide.SELL,
                    volume=float(pos.get('qty', 0)),
                    entry_price=float(pos.get('avgPrice', 0)),
                    current_price=float(pos.get('currentPrice', 0)) if pos.get('currentPrice') else None,
                    stop_loss=float(pos.get('stopLoss', 0)) if pos.get('stopLoss') else None,
                    take_profit=float(pos.get('takeProfit', 0)) if pos.get('takeProfit') else None,
                    profit=float(pos.get('unrealizedPnl', 0)) if pos.get('unrealizedPnl') else 0,
                    opened_at=datetime.now(timezone.utc)  # Simplified
                ))
            
            return positions
            
        except Exception as e:
            print(f"[TradeLocker] Error getting positions: {e}")
            return []
    
    async def close_position(self, position_id: str) -> OrderResult:
        """Close a position"""
        if not self._api:
            return OrderResult(success=False, message="Not connected")
        
        try:
            result = self._api.close_position(int(position_id))
            
            if result:
                return OrderResult(
                    success=True,
                    order_id=position_id,
                    message="Position closed"
                )
            else:
                return OrderResult(
                    success=False,
                    message="Failed to close position"
                )
                
        except Exception as e:
            return OrderResult(
                success=False,
                message=str(e)
            )
    
    async def modify_position(
        self,
        position_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> OrderResult:
        """Modify position SL/TP"""
        if not self._api:
            return OrderResult(success=False, message="Not connected")
        
        try:
            # TradeLocker library might have modify_position method
            # For now, this is a placeholder
            result = self._api.set_position_protection(
                position_id=int(position_id),
                stop_loss=stop_loss,
                take_profit=take_profit
            )
            
            if result:
                return OrderResult(
                    success=True,
                    message="Position modified"
                )
            else:
                return OrderResult(
                    success=False,
                    message="Failed to modify position"
                )
                
        except Exception as e:
            return OrderResult(
                success=False,
                message=str(e)
            )


# =============================================================================
# Synchronous Wrapper
# =============================================================================

import asyncio

class TradeLockerBrokerSync(TradeLockerBroker):
    """Synchronous wrapper for TradeLockerBroker"""
    
    def __init__(self, broker_id: str, config: dict):
        super().__init__(broker_id, config)
        self._loop = None
    
    def _get_loop(self):
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop
    
    def connect(self) -> bool:
        return self._get_loop().run_until_complete(super().connect())
    
    def disconnect(self):
        return self._get_loop().run_until_complete(super().disconnect())
    
    def get_account_info(self) -> Optional[AccountInfo]:
        return self._get_loop().run_until_complete(super().get_account_info())
    
    def get_symbols(self) -> List[str]:
        return self._get_loop().run_until_complete(super().get_symbols())
    
    def get_symbol_info(self, symbol: str) -> Optional[SymbolInfo]:
        return self._get_loop().run_until_complete(super().get_symbol_info(symbol))
    
    def place_order(self, order: OrderRequest) -> OrderResult:
        return self._get_loop().run_until_complete(super().place_order(order))
    
    def cancel_order(self, order_id: str) -> OrderResult:
        return self._get_loop().run_until_complete(super().cancel_order(order_id))
    
    def get_pending_orders(self) -> List[PendingOrder]:
        return self._get_loop().run_until_complete(super().get_pending_orders())
    
    def get_positions(self) -> List[Position]:
        return self._get_loop().run_until_complete(super().get_positions())
    
    def close_position(self, position_id: str) -> OrderResult:
        return self._get_loop().run_until_complete(super().close_position(position_id))
    
    def modify_position(
        self,
        position_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> OrderResult:
        return self._get_loop().run_until_complete(
            super().modify_position(position_id, stop_loss, take_profit)
        )
