#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeLocker REST API broker implementation
"""

import base64
import json
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from .base import (
    BaseBroker, OrderRequest, OrderResult, OrderSide, OrderType, OrderStatus,
    Position, PendingOrder, AccountInfo, SymbolInfo
)


class TradeLockerBroker(BaseBroker):
    """TradeLocker REST API broker implementation"""
    
    # API endpoints
    AUTH_URL = "https://demo.tradelocker.com/backend-api/auth/jwt/token"
    REFRESH_URL = "https://demo.tradelocker.com/backend-api/auth/jwt/refresh"
    
    def __init__(self, broker_id: str, config: dict):
        super().__init__(broker_id, config)
        
        self.email = config.get("email", "")
        self.password = config.get("password", "")
        self.server = config.get("server", "GFTTL")
        
        # Account ID from config (optional - if not set, will use first active account)
        self._configured_account_id = config.get("account_id")
        
        # API state
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._base_url: Optional[str] = None
        self._account_id: Optional[str] = None
        self._acc_num: Optional[int] = None
        
        # Cache
        self._field_config: Dict = {}
        self._instruments_map: Dict[str, str] = {}  # id -> name
        self._instruments_reverse_map: Dict[str, str] = {}  # name -> id
    
    def _decode_jwt_payload(self, token: str) -> Optional[dict]:
        """Decode JWT payload to extract host info"""
        try:
            parts = token.split('.')
            if len(parts) != 3:
                return None
            
            payload = parts[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += '=' * padding
            
            decoded = base64.urlsafe_b64decode(payload)
            return json.loads(decoded)
        except Exception as e:
            print(f"[TradeLocker] JWT decode error: {e}")
            return None
    
    async def connect(self) -> bool:
        """Authenticate with TradeLocker"""
        payload = {
            "email": self.email,
            "password": self.password,
            "server": self.server
        }
        
        try:
            response = requests.post(self.AUTH_URL, json=payload, timeout=15)
            
            if response.status_code not in [200, 201]:
                print(f"[TradeLocker] ❌ Auth failed: {response.status_code} - {response.text}")
                return False
            
            data = response.json()
            self._access_token = data.get('accessToken')
            self._refresh_token = data.get('refreshToken')
            
            # Extract host from JWT
            jwt_payload = self._decode_jwt_payload(self._access_token)
            if jwt_payload and 'host' in jwt_payload:
                self._base_url = f"https://{jwt_payload['host']}"
            else:
                self._base_url = "https://demo.tradelocker.com"
            
            print(f"[TradeLocker] ✅ Authenticated to {self._base_url}")
            
            # Get accounts
            accounts = await self._get_accounts()
            if not accounts:
                print("[TradeLocker] ❌ No accounts found")
                return False
            
            # Afficher tous les comptes disponibles
            print(f"[TradeLocker] Found {len(accounts)} account(s):")
            for acc in accounts:
                status = "✅" if acc.get('status') == 'ACTIVE' or acc.get('accNum') else "❌"
                print(f"   {status} ID: {acc.get('id')} | accNum: {acc.get('accNum')} | {acc.get('name', 'N/A')}")
            
            # Sélectionner le compte
            selected_account = None
            
            # 1. Si account_id est configuré, l'utiliser
            if self._configured_account_id:
                for acc in accounts:
                    if str(acc.get('id')) == str(self._configured_account_id):
                        selected_account = acc
                        break
                if not selected_account:
                    print(f"[TradeLocker] ⚠️  Configured account_id {self._configured_account_id} not found")
            
            # 2. Sinon, prendre le premier compte actif ou le premier tout court
            if not selected_account:
                # Essayer de trouver un compte actif
                for acc in accounts:
                    if acc.get('status') == 'ACTIVE':
                        selected_account = acc
                        break
                # Sinon prendre le premier
                if not selected_account:
                    selected_account = accounts[0]
            
            self._account_id = selected_account.get('id')
            self._acc_num = selected_account.get('accNum')
            print(f"[TradeLocker] ✅ Using account: {self._acc_num} (ID: {self._account_id})")
            
            # Load field config and instruments
            self._field_config = await self._get_field_config()
            await self._load_instruments()
            
            self._connected = True
            return True
            
        except requests.exceptions.RequestException as e:
            print(f"[TradeLocker] ❌ Connection error: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from TradeLocker"""
        self._access_token = None
        self._connected = False
    
    def _headers(self) -> dict:
        """Get request headers"""
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "accept": "application/json"
        }
        if self._acc_num:
            headers["accNum"] = str(self._acc_num)
        return headers
    
    async def _get_accounts(self) -> List[dict]:
        """Get list of accounts"""
        url = f"{self._base_url}/backend-api/auth/jwt/all-accounts"
        try:
            response = requests.get(url, headers=self._headers(), timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get('accounts', [])
        except Exception as e:
            print(f"[TradeLocker] Error getting accounts: {e}")
            return []
    
    async def _get_field_config(self) -> dict:
        """Get field schema for parsing responses"""
        url = f"{self._base_url}/backend-api/trade/config"
        try:
            response = requests.get(url, headers=self._headers(), timeout=10)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and 'd' in data:
                    return data['d']
            return {}
        except Exception:
            return {}
    
    async def _load_instruments(self):
        """Load and cache instrument mapping"""
        url = f"{self._base_url}/backend-api/trade/accounts/{self._account_id}/instruments"
        try:
            response = requests.get(url, headers=self._headers(), timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if isinstance(data, dict) and 'd' in data:
                instruments = data['d'].get('instruments', [])
                for inst in instruments:
                    if isinstance(inst, list) and len(inst) >= 2:
                        inst_id = str(inst[0])
                        inst_name = inst[1] if len(inst) > 1 else f"ID:{inst_id}"
                        self._instruments_map[inst_id] = inst_name
                        self._instruments_reverse_map[inst_name] = inst_id
                
                print(f"[TradeLocker] Loaded {len(self._instruments_map)} instruments")
        except Exception as e:
            print(f"[TradeLocker] Error loading instruments: {e}")
    
    def _get_instrument_id(self, symbol: str) -> Optional[str]:
        """Get instrument ID from symbol name"""
        # Check direct mapping in config
        mapping = self.config.get("instruments_mapping", {})
        if symbol in mapping:
            broker_symbol = mapping[symbol]
            # If mapping gives a name like "EURUSD.X", convert to ID
            if broker_symbol in self._instruments_reverse_map:
                return self._instruments_reverse_map[broker_symbol]
            # If it's already an ID
            if broker_symbol in self._instruments_map:
                return broker_symbol
            # Return as-is (might be an ID)
            return str(broker_symbol)
        
        # Try reverse map directly
        if symbol in self._instruments_reverse_map:
            return self._instruments_reverse_map[symbol]
        
        # Try with .X suffix
        if f"{symbol}.X" in self._instruments_reverse_map:
            return self._instruments_reverse_map[f"{symbol}.X"]
        
        return None
    
    def _get_instrument_name(self, inst_id: str) -> str:
        """Get instrument name from ID"""
        return self._instruments_map.get(str(inst_id), f"ID:{inst_id}")
    
    def _parse_order_array(self, order_array: list) -> dict:
        """Parse order array into dict"""
        field_names = self._field_config.get('orders', [])
        
        if not field_names:
            # Fallback structure
            return {
                'id': order_array[0] if len(order_array) > 0 else None,
                'tradableInstrumentId': order_array[1] if len(order_array) > 1 else None,
                'routeId': order_array[2] if len(order_array) > 2 else None,
                'qty': order_array[3] if len(order_array) > 3 else None,
                'side': order_array[4] if len(order_array) > 4 else None,
                'orderType': order_array[5] if len(order_array) > 5 else None,
                'status': order_array[6] if len(order_array) > 6 else None,
                'limitPrice': order_array[9] if len(order_array) > 9 else None,
                'stopPrice': order_array[10] if len(order_array) > 10 else None,
                'timeInForce': order_array[11] if len(order_array) > 11 else None,
                'createTime': order_array[13] if len(order_array) > 13 else None,
                'updateTime': order_array[14] if len(order_array) > 14 else None,
                'isStandalone': order_array[15] if len(order_array) > 15 else None,
                'positionId': order_array[16] if len(order_array) > 16 else None,
                'slPrice': order_array[17] if len(order_array) > 17 else None,
                'tpPrice': order_array[19] if len(order_array) > 19 else None,
            }
        
        order_dict = {}
        for i, field_name in enumerate(field_names):
            if i < len(order_array):
                order_dict[field_name] = order_array[i]
        return order_dict
    
    def _parse_position_array(self, pos_array: list) -> dict:
        """Parse position array into dict"""
        field_names = self._field_config.get('positions', [])
        
        if not field_names:
            # Fallback structure
            return {
                'id': pos_array[0] if len(pos_array) > 0 else None,
                'tradableInstrumentId': pos_array[1] if len(pos_array) > 1 else None,
                'side': pos_array[3] if len(pos_array) > 3 else None,
                'qty': pos_array[4] if len(pos_array) > 4 else None,
                'avgPrice': pos_array[5] if len(pos_array) > 5 else None,
                'unrealizedPnl': pos_array[7] if len(pos_array) > 7 else None,
            }
        
        pos_dict = {}
        for i, field_name in enumerate(field_names):
            if i < len(pos_array):
                pos_dict[field_name] = pos_array[i]
        return pos_dict
    
    async def get_account_info(self) -> Optional[AccountInfo]:
        """Get account information"""
        if not self._connected:
            return None
        
        url = f"{self._base_url}/backend-api/trade/accounts/{self._account_id}/state"
        
        try:
            response = requests.get(url, headers=self._headers(), timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if isinstance(data, dict) and 'd' in data:
                state = data['d']
                
                self._account_info = AccountInfo(
                    account_id=self._account_id,
                    broker_name=self.name,
                    balance=state.get('balance', 0),
                    equity=state.get('equity', 0),
                    margin_used=state.get('usedMargin', 0),
                    margin_free=state.get('freeMargin', 0),
                    currency=state.get('currency', 'USD'),
                    leverage=state.get('leverage', 100),
                    is_demo=self.is_demo
                )
                return self._account_info
            
            return None
        except Exception as e:
            print(f"[TradeLocker] Error getting account info: {e}")
            return None
    
    async def get_symbols(self) -> List[SymbolInfo]:
        """Get available symbols"""
        symbols = []
        for inst_id, inst_name in self._instruments_map.items():
            symbols.append(SymbolInfo(
                symbol=inst_name,
                broker_symbol=inst_id,
                description="",
                is_tradable=True
            ))
        return symbols
    
    async def get_symbol_info(self, symbol: str) -> Optional[SymbolInfo]:
        """Get info for specific symbol"""
        inst_id = self._get_instrument_id(symbol)
        if inst_id:
            inst_name = self._get_instrument_name(inst_id)
            return SymbolInfo(
                symbol=inst_name,
                broker_symbol=inst_id,
                is_tradable=True
            )
        return None
    
    async def place_order(self, order: OrderRequest) -> OrderResult:
        """Place an order on TradeLocker"""
        if not self._connected:
            return OrderResult(success=False, message="Not connected")
        
        # Get instrument ID
        inst_id = self._get_instrument_id(order.symbol)
        if not inst_id:
            # Try broker_symbol directly
            if order.broker_symbol:
                inst_id = order.broker_symbol
            else:
                return OrderResult(
                    success=False,
                    message=f"Symbol {order.symbol} not found for TradeLocker"
                )
        
        url = f"{self._base_url}/backend-api/trade/accounts/{self._account_id}/orders"
        
        # Build order payload
        payload = {
            "tradableInstrumentId": int(inst_id),
            "side": order.side.value.lower(),  # "buy" or "sell"
            "qty": order.volume,
        }
        
        # Order type
        if order.order_type == OrderType.MARKET:
            payload["type"] = "market"
        elif order.order_type == OrderType.LIMIT:
            payload["type"] = "limit"
            if order.entry_price:
                payload["price"] = order.entry_price
        elif order.order_type == OrderType.STOP:
            payload["type"] = "stop"
            if order.entry_price:
                payload["stopPrice"] = order.entry_price
        
        # Stop loss and take profit
        if order.stop_loss:
            payload["stopLoss"] = order.stop_loss
            payload["stopLossType"] = "absolute"
        if order.take_profit:
            payload["takeProfit"] = order.take_profit
            payload["takeProfitType"] = "absolute"
        
        # Note: TradeLocker doesn't support native order expiration
        # We'll handle this through the order cleanup service
        
        print(f"[TradeLocker] Placing {order.order_type.value} {order.side.value} "
              f"{order.volume} lots on {order.symbol} @ {order.entry_price}")
        
        try:
            response = requests.post(url, headers=self._headers(), json=payload, timeout=30)
            
            if response.status_code in [200, 201]:
                data = response.json()
                order_id = None
                
                if isinstance(data, dict) and 'd' in data:
                    order_data = data['d']
                    if isinstance(order_data, dict):
                        order_id = order_data.get('orderId') or order_data.get('id')
                
                return OrderResult(
                    success=True,
                    order_id=str(order_id) if order_id else None,
                    message="Order placed successfully",
                    broker_response=data
                )
            else:
                error_text = response.text
                try:
                    error_data = response.json()
                    error_text = error_data.get('message', error_text)
                except:
                    pass
                
                return OrderResult(
                    success=False,
                    message=f"Order failed: {response.status_code} - {error_text}",
                    error_code=str(response.status_code)
                )
                
        except requests.exceptions.Timeout:
            return OrderResult(success=False, message="Order timeout")
        except Exception as e:
            return OrderResult(success=False, message=str(e))
    
    async def cancel_order(self, order_id: str, max_retries: int = 2) -> OrderResult:
        """Cancel a pending order"""
        if not self._connected:
            return OrderResult(success=False, message="Not connected")
        
        url = f"{self._base_url}/backend-api/trade/orders/{order_id}"
        
        for attempt in range(max_retries):
            try:
                response = requests.delete(url, headers=self._headers(), timeout=30)
                
                if response.status_code in [200, 204]:
                    return OrderResult(
                        success=True,
                        order_id=order_id,
                        message="Order cancelled"
                    )
                elif response.status_code == 404:
                    return OrderResult(
                        success=True,
                        order_id=order_id,
                        message="Order already cancelled or filled"
                    )
                else:
                    if attempt == max_retries - 1:
                        return OrderResult(
                            success=False,
                            message=f"Cancel failed: {response.status_code}",
                            error_code=str(response.status_code)
                        )
                        
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    print(f"[TradeLocker] Cancel timeout, retry {attempt + 1}/{max_retries}")
                    import time
                    time.sleep(2)
                else:
                    return OrderResult(success=False, message="Cancel timeout")
            except Exception as e:
                return OrderResult(success=False, message=str(e))
        
        return OrderResult(success=False, message="Cancel failed after retries")
    
    async def get_pending_orders(self) -> List[PendingOrder]:
        """Get all pending orders"""
        if not self._connected:
            return []
        
        url = f"{self._base_url}/backend-api/trade/accounts/{self._account_id}/orders"
        
        try:
            response = requests.get(url, headers=self._headers(), timeout=10)
            response.raise_for_status()
            data = response.json()
            
            orders = []
            if isinstance(data, dict) and 'd' in data:
                orders_arrays = data['d'].get('orders', [])
                
                for arr in orders_arrays:
                    order_dict = self._parse_order_array(arr)
                    
                    # Filter: only pending standalone orders (limit/stop, status=New, no position)
                    if (order_dict.get('orderType') in ['limit', 'stop'] and
                        order_dict.get('status') == 'New' and
                        order_dict.get('positionId') is None):
                        
                        side = OrderSide.BUY if order_dict.get('side') == 'buy' else OrderSide.SELL
                        order_type = OrderType.LIMIT if order_dict.get('orderType') == 'limit' else OrderType.STOP
                        
                        created_time = None
                        if order_dict.get('createTime'):
                            created_time = datetime.fromtimestamp(
                                int(order_dict['createTime']) / 1000, 
                                tz=timezone.utc
                            )
                        
                        inst_id = str(order_dict.get('tradableInstrumentId', ''))
                        symbol = self._get_instrument_name(inst_id)
                        unified_symbol = self.reverse_map_symbol(symbol) or symbol
                        
                        orders.append(PendingOrder(
                            order_id=str(order_dict.get('id', '')),
                            symbol=unified_symbol,
                            side=side,
                            order_type=order_type,
                            volume=float(order_dict.get('qty', 0)),
                            entry_price=float(order_dict.get('limitPrice') or order_dict.get('stopPrice') or 0),
                            stop_loss=float(order_dict.get('slPrice')) if order_dict.get('slPrice') else None,
                            take_profit=float(order_dict.get('tpPrice')) if order_dict.get('tpPrice') else None,
                            created_time=created_time,
                            broker_id=self.broker_id,
                            raw_data=order_dict
                        ))
            
            return orders
            
        except Exception as e:
            print(f"[TradeLocker] Error getting orders: {e}")
            return []
    
    async def get_positions(self) -> List[Position]:
        """Get all open positions"""
        if not self._connected:
            return []
        
        url = f"{self._base_url}/backend-api/trade/accounts/{self._account_id}/positions"
        
        try:
            response = requests.get(url, headers=self._headers(), timeout=10)
            response.raise_for_status()
            data = response.json()
            
            positions = []
            if isinstance(data, dict) and 'd' in data:
                positions_arrays = data['d'].get('positions', [])
                
                for arr in positions_arrays:
                    pos_dict = self._parse_position_array(arr)
                    
                    side = OrderSide.BUY if pos_dict.get('side') == 'buy' else OrderSide.SELL
                    inst_id = str(pos_dict.get('tradableInstrumentId', ''))
                    symbol = self._get_instrument_name(inst_id)
                    
                    positions.append(Position(
                        position_id=str(pos_dict.get('id', '')),
                        symbol=symbol,
                        side=side,
                        volume=float(pos_dict.get('qty', 0)),
                        entry_price=float(pos_dict.get('avgPrice', 0)),
                        profit=float(pos_dict.get('unrealizedPnl', 0))
                    ))
            
            return positions
            
        except Exception as e:
            print(f"[TradeLocker] Error getting positions: {e}")
            return []


# Synchronous wrapper for CLI usage
class TradeLockerBrokerSync:
    """Synchronous wrapper for TradeLockerBroker for use in scripts"""
    
    def __init__(self, broker_id: str, config: dict):
        self.broker = TradeLockerBroker(broker_id, config)
        self._loop = None
    
    def _get_loop(self):
        import asyncio
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop
    
    def connect(self) -> bool:
        return self._get_loop().run_until_complete(self.broker.connect())
    
    def disconnect(self):
        self._get_loop().run_until_complete(self.broker.disconnect())
    
    def get_account_info(self) -> Optional[AccountInfo]:
        return self._get_loop().run_until_complete(self.broker.get_account_info())
    
    def get_symbols(self) -> List[SymbolInfo]:
        return self._get_loop().run_until_complete(self.broker.get_symbols())
    
    def get_symbol_info(self, symbol: str) -> Optional[SymbolInfo]:
        return self._get_loop().run_until_complete(self.broker.get_symbol_info(symbol))
    
    def place_order(self, order: OrderRequest) -> OrderResult:
        return self._get_loop().run_until_complete(self.broker.place_order(order))
    
    def cancel_order(self, order_id: str) -> OrderResult:
        return self._get_loop().run_until_complete(self.broker.cancel_order(order_id))
    
    def get_pending_orders(self) -> List[PendingOrder]:
        return self._get_loop().run_until_complete(self.broker.get_pending_orders())
    
    def get_positions(self) -> List[Position]:
        return self._get_loop().run_until_complete(self.broker.get_positions())
