#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cTrader Open API broker implementation
Uses Twisted for async communication
"""

import asyncio
import time
import requests
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Callable
from concurrent.futures import Future
import threading

from .base import (
    BaseBroker, OrderRequest, OrderResult, OrderSide, OrderType, OrderStatus,
    Position, PendingOrder, AccountInfo, SymbolInfo
)

try:
    from twisted.internet import reactor, threads
    from twisted.internet.defer import Deferred
    from ctrader_open_api import Client, TcpProtocol, EndPoints, Protobuf
    from ctrader_open_api.messages.OpenApiMessages_pb2 import (
        ProtoOAApplicationAuthReq,
        ProtoOAAccountAuthReq,
        ProtoOAGetAccountListByAccessTokenReq,
        ProtoOASymbolsListReq,
        ProtoOANewOrderReq,
        ProtoOACancelOrderReq,
        ProtoOAReconcileReq,
        ProtoOATraderReq,
        ProtoOAErrorRes,
        ProtoOAAssetListReq,
    )
    CTRADER_AVAILABLE = True
except ImportError:
    CTRADER_AVAILABLE = False
    print("⚠️  ctrader-open-api not installed. cTrader support disabled.")


class CTraderBroker(BaseBroker):
    """cTrader Open API broker implementation"""
    
    def __init__(self, broker_id: str, config: dict):
        super().__init__(broker_id, config)
        
        if not CTRADER_AVAILABLE:
            raise ImportError("ctrader-open-api is required for cTrader support")
        
        self.client_id = config.get("client_id", "")
        self.client_secret = config.get("client_secret", "")
        self.access_token = config.get("access_token", "")
        self.refresh_token = config.get("refresh_token", "")
        
        # account_id doit être un int
        acc_id = config.get("account_id")
        self.account_id = int(acc_id) if acc_id else None
        
        # Connection settings
        self.is_demo = config.get("is_demo", True)
        self.host = EndPoints.PROTOBUF_DEMO_HOST if self.is_demo else EndPoints.PROTOBUF_LIVE_HOST
        self.port = EndPoints.PROTOBUF_PORT
        
        # Client and state
        self._client: Optional[Client] = None
        self._pending_requests: Dict[str, Future] = {}
        self._symbols: Dict[int, SymbolInfo] = {}
        self._message_handlers: Dict[str, Callable] = {}
        
        # Thread management for Twisted reactor
        self._reactor_thread: Optional[threading.Thread] = None
        self._reactor_running = False
        self._token_refreshed = False  # Éviter de refresh plusieurs fois par session
    
    def _should_refresh_token(self) -> bool:
        """Check if we should refresh the token"""
        if not self.refresh_token:
            return False
        if not self.config.get("auto_refresh_token", True):
            return False
        if self._token_refreshed:
            # Déjà refreshé dans cette session
            return False
        return True
    
    def _ensure_reactor_running(self):
        """Ensure Twisted reactor is running in a background thread"""
        if self._reactor_running:
            return
        
        def run_reactor():
            from twisted.internet import reactor
            if not reactor.running:
                reactor.run(installSignalHandlers=False)
        
        self._reactor_thread = threading.Thread(target=run_reactor, daemon=True)
        self._reactor_thread.start()
        self._reactor_running = True
        time.sleep(0.5)  # Give reactor time to start
    
    def _refresh_access_token(self) -> bool:
        """Refresh the access token using the refresh token.
        
        cTrader refresh tokens are single-use. After refresh, both the new
        access_token and new refresh_token are saved to the config file.
        """
        if not self.refresh_token:
            print("[cTrader] ⚠️  No refresh token available")
            return False
        
        # Garder les anciens tokens au cas où le refresh échoue
        old_access_token = self.access_token
        old_refresh_token = self.refresh_token
        
        token_url = "https://openapi.ctrader.com/apps/token"
        
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        
        try:
            print("[cTrader] Refreshing access token...")
            response = requests.post(token_url, data=payload, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                
                if not data:
                    print("[cTrader] ❌ Empty response from token endpoint")
                    return False
                
                new_access = data.get("accessToken") or data.get("access_token")
                new_refresh = data.get("refreshToken") or data.get("refresh_token")
                
                if not new_access:
                    print("[cTrader] ❌ No access token in response")
                    return False
                
                self.access_token = new_access
                if new_refresh:
                    self.refresh_token = new_refresh
                
                print(f"[cTrader] ✅ Token refreshed successfully")
                print(f"[cTrader]    New access token: {self.access_token[:20]}...")
                
                # Sauvegarder les nouveaux tokens dans la config
                self._save_tokens_to_config()
                
                return True
            else:
                print(f"[cTrader] ❌ Token refresh failed: {response.status_code}")
                print(f"[cTrader]    Response: {response.text}")
                # Garder les anciens tokens
                return False
                
        except Exception as e:
            print(f"[cTrader] ❌ Token refresh error: {e}")
            # Restaurer les anciens tokens
            self.access_token = old_access_token
            self.refresh_token = old_refresh_token
            return False
    
    def _save_tokens_to_config(self):
        """Save the new tokens to the config file"""
        try:
            from config import update_broker_tokens
            update_broker_tokens(
                broker_id=self.broker_id,
                access_token=self.access_token,
                refresh_token=self.refresh_token
            )
            print(f"[cTrader] 💾 Tokens saved to config")
        except Exception as e:
            print(f"[cTrader] ⚠️  Could not save tokens: {e}")
    
    def _enum_value(self, message_obj, field_name: str, wanted: str) -> int:
        """Get enum value by name from protobuf message"""
        field = message_obj.DESCRIPTOR.fields_by_name[field_name]
        if field.enum_type is None:
            raise ValueError(f"Field {field_name} is not an enum")
        
        wanted_u = wanted.upper()
        values = list(field.enum_type.values)
        
        # Exact match
        for v in values:
            if v.name.upper() == wanted_u:
                return v.number
        
        # Suffix/contains match
        for v in values:
            name_u = v.name.upper()
            if name_u.endswith("_" + wanted_u) or name_u.endswith(wanted_u) or wanted_u in name_u:
                return v.number
        
        available = ", ".join([f"{v.name}={v.number}" for v in values])
        raise ValueError(f"Enum not found for {field_name}={wanted}. Available: {available}")
    
    async def connect(self) -> bool:
        """Connect and authenticate with cTrader"""
        
        # Auto-refresh token si nécessaire (une seule fois par session)
        if self._should_refresh_token():
            if self._refresh_access_token():
                self._token_refreshed = True
        
        self._ensure_reactor_running()
        
        # Create client
        self._client = Client(self.host, self.port, TcpProtocol)
        
        # Set up callbacks
        connect_future = asyncio.get_event_loop().create_future()
        auth_future = asyncio.get_event_loop().create_future()
        account_auth_future = asyncio.get_event_loop().create_future()
        
        def on_connected(client):
            print(f"[cTrader] Connected to {self.host}:{self.port}")
            
            # Authenticate application
            req = ProtoOAApplicationAuthReq()
            req.clientId = self.client_id
            req.clientSecret = self.client_secret
            client.send(req)
        
        def on_message(client, message):
            payload = Protobuf.extract(message)
            ptype = payload.DESCRIPTOR.name
            
            if isinstance(payload, ProtoOAErrorRes):
                error_msg = f"cTrader Error: {payload.errorCode} - {payload.description}"
                print(f"[cTrader] ❌ {error_msg}")
                if not connect_future.done():
                    connect_future.set_exception(Exception(error_msg))
                return
            
            if ptype == "ProtoOAApplicationAuthRes":
                print("[cTrader] ✅ Application authenticated")
                
                if self.account_id:
                    # Account ID provided, authenticate directly
                    req = ProtoOAAccountAuthReq()
                    req.ctidTraderAccountId = self.account_id
                    req.accessToken = self.access_token
                    client.send(req)
                else:
                    # No account ID, get account list first
                    print("[cTrader] Getting account list...")
                    req = ProtoOAGetAccountListByAccessTokenReq()
                    req.accessToken = self.access_token
                    client.send(req)
            
            elif ptype == "ProtoOAGetAccountListByAccessTokenRes":
                accounts = list(payload.ctidTraderAccount)
                if not accounts:
                    print("[cTrader] ❌ No accounts found for this token")
                    if not connect_future.done():
                        connect_future.set_exception(Exception("No accounts found"))
                    return
                
                # Use first account
                self.account_id = accounts[0].ctidTraderAccountId
                print(f"[cTrader] Found {len(accounts)} account(s), using: {self.account_id}")
                
                req = ProtoOAAccountAuthReq()
                req.ctidTraderAccountId = self.account_id
                req.accessToken = self.access_token
                client.send(req)
                
            elif ptype == "ProtoOAAccountAuthRes":
                print(f"[cTrader] ✅ Account {self.account_id} authenticated")
                self._connected = True
                if not connect_future.done():
                    connect_future.set_result(True)
                
            elif ptype == "ProtoOASymbolsListRes":
                self._process_symbols_response(payload)
                if "symbols" in self._pending_requests:
                    self._pending_requests["symbols"].set_result(list(self._symbols.values()))
                
            elif ptype == "ProtoOATraderRes":
                self._process_trader_response(payload)
                if "account_info" in self._pending_requests:
                    self._pending_requests["account_info"].set_result(self._account_info)
                
            elif ptype == "ProtoOAReconcileRes":
                self._process_reconcile_response(payload)
                if "reconcile" in self._pending_requests:
                    self._pending_requests["reconcile"].set_result(payload)
                
            elif "Order" in ptype or "Execution" in ptype:
                self._process_order_response(payload, ptype)
        
        self._client.setConnectedCallback(on_connected)
        self._client.setMessageReceivedCallback(on_message)
        
        # Start connection
        from twisted.internet import reactor
        reactor.callFromThread(self._client.startService)
        
        try:
            await asyncio.wait_for(connect_future, timeout=30)
            return True
        except asyncio.TimeoutError:
            print("[cTrader] ❌ Connection timeout")
            return False
        except Exception as e:
            print(f"[cTrader] ❌ Connection error: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from cTrader"""
        if self._client:
            from twisted.internet import reactor
            reactor.callFromThread(self._client.stopService)
        self._connected = False
    
    def _process_symbols_response(self, payload):
        """Process symbols list response"""
        for s in payload.symbol:
            symbol_id = s.symbolId
            symbol_name = getattr(s, "symbolName", f"ID:{symbol_id}")
            
            self._symbols[symbol_id] = SymbolInfo(
                symbol=symbol_name,
                broker_symbol=str(symbol_id),
                description=getattr(s, "description", ""),
                digits=getattr(s, "digits", 5),
                pip_size=10 ** (-getattr(s, "digits", 5)),
                is_tradable=True
            )
    
    def _process_trader_response(self, payload):
        """Process trader (account) info response"""
        trader = payload.trader
        self._account_info = AccountInfo(
            account_id=str(self.account_id),
            broker_name=self.name,
            balance=trader.balance / 100,  # Convert from cents
            equity=trader.balance / 100,
            margin_used=getattr(trader, "usedMargin", 0) / 100,
            currency=getattr(trader, "depositAssetId", "USD"),
            leverage=getattr(trader, "leverageInCents", 10000) // 100,
            is_demo=self.is_demo
        )
    
    def _process_reconcile_response(self, payload):
        """Process reconcile response (positions and orders)"""
        self._positions = []
        self._pending_orders = []
        
        # Process positions
        for pos in payload.position:
            side = OrderSide.BUY if pos.tradeData.tradeSide == 1 else OrderSide.SELL
            self._positions.append(Position(
                position_id=str(pos.positionId),
                symbol=self.reverse_map_symbol(pos.tradeData.symbolId) or str(pos.tradeData.symbolId),
                side=side,
                volume=pos.tradeData.volume / 100,  # Convert to lots
                entry_price=pos.price,
                stop_loss=getattr(pos, "stopLoss", None),
                take_profit=getattr(pos, "takeProfit", None),
            ))
        
        # Process pending orders
        for order in payload.order:
            side = OrderSide.BUY if order.tradeData.tradeSide == 1 else OrderSide.SELL
            order_type = OrderType.LIMIT if order.orderType == 1 else OrderType.STOP
            
            self._pending_orders.append(PendingOrder(
                order_id=str(order.orderId),
                symbol=self.reverse_map_symbol(order.tradeData.symbolId) or str(order.tradeData.symbolId),
                side=side,
                order_type=order_type,
                volume=order.tradeData.volume / 100,
                entry_price=getattr(order, "limitPrice", getattr(order, "stopPrice", 0)),
                stop_loss=getattr(order, "stopLoss", None),
                take_profit=getattr(order, "takeProfit", None),
                created_time=datetime.fromtimestamp(order.tradeData.openTimestamp / 1000, tz=timezone.utc),
                label=getattr(order, "label", ""),
                comment=getattr(order, "comment", ""),
                broker_id=self.broker_id,
            ))
    
    def _process_order_response(self, payload, ptype: str):
        """Process order-related responses"""
        if "order_place" in self._pending_requests:
            future = self._pending_requests.pop("order_place")
            
            if hasattr(payload, "orderId"):
                future.set_result(OrderResult(
                    success=True,
                    order_id=str(payload.orderId),
                    message="Order placed successfully",
                    broker_response=payload
                ))
            elif hasattr(payload, "position"):
                future.set_result(OrderResult(
                    success=True,
                    order_id=str(payload.position.positionId),
                    message="Order filled immediately",
                    broker_response=payload
                ))
            else:
                future.set_result(OrderResult(
                    success=True,
                    message=f"Response: {ptype}",
                    broker_response=payload
                ))
        
        if "order_cancel" in self._pending_requests:
            future = self._pending_requests.pop("order_cancel")
            future.set_result(OrderResult(
                success=True,
                message="Order cancelled",
                broker_response=payload
            ))
    
    async def get_account_info(self) -> Optional[AccountInfo]:
        """Get account information"""
        if not self._connected:
            return None
        
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_requests["account_info"] = future
        
        req = ProtoOATraderReq()
        req.ctidTraderAccountId = self.account_id
        
        from twisted.internet import reactor
        reactor.callFromThread(self._client.send, req)
        
        try:
            return await asyncio.wait_for(future, timeout=10)
        except asyncio.TimeoutError:
            return None
    
    async def get_symbols(self) -> List[SymbolInfo]:
        """Get available symbols"""
        if not self._connected:
            return []
        
        if self._symbols:
            return list(self._symbols.values())
        
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_requests["symbols"] = future
        
        req = ProtoOASymbolsListReq()
        req.ctidTraderAccountId = self.account_id
        
        from twisted.internet import reactor
        reactor.callFromThread(self._client.send, req)
        
        try:
            return await asyncio.wait_for(future, timeout=15)
        except asyncio.TimeoutError:
            return []
    
    async def get_symbol_info(self, symbol: str) -> Optional[SymbolInfo]:
        """Get info for specific symbol"""
        if not self._symbols:
            await self.get_symbols()
        
        # Try to find by name
        for s in self._symbols.values():
            if s.symbol == symbol or s.broker_symbol == symbol:
                return s
        
        # Try mapping
        broker_symbol = self.map_symbol(symbol)
        if broker_symbol and int(broker_symbol) in self._symbols:
            return self._symbols[int(broker_symbol)]
        
        return None
    
    async def place_order(self, order: OrderRequest) -> OrderResult:
        """Place an order on cTrader"""
        if not self._connected:
            return OrderResult(success=False, message="Not connected")
        
        # Get broker symbol
        broker_symbol = order.broker_symbol or self.map_symbol(order.symbol)
        if not broker_symbol:
            return OrderResult(
                success=False, 
                message=f"Symbol {order.symbol} not mapped for cTrader"
            )
        
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_requests["order_place"] = future
        
        try:
            req = ProtoOANewOrderReq()
            req.ctidTraderAccountId = self.account_id
            req.symbolId = int(broker_symbol)
            
            # Order type
            if order.order_type == OrderType.MARKET:
                req.orderType = self._enum_value(req, "orderType", "MARKET")
            elif order.order_type == OrderType.LIMIT:
                req.orderType = self._enum_value(req, "orderType", "LIMIT")
                if order.entry_price:
                    req.limitPrice = order.entry_price
            elif order.order_type == OrderType.STOP:
                req.orderType = self._enum_value(req, "orderType", "STOP")
                if order.entry_price:
                    req.stopPrice = order.entry_price
            
            # Side
            req.tradeSide = self._enum_value(req, "tradeSide", order.side.value)
            
            # Volume (convert lots to broker units - usually x100)
            broker_volume = order.broker_volume or int(order.volume * 100)
            req.volume = broker_volume
            
            # Stop loss and take profit
            if order.stop_loss:
                req.stopLoss = order.stop_loss
            if order.take_profit:
                req.takeProfit = order.take_profit
            
            # Expiration
            if order.expiry_timestamp_ms:
                req.timeInForce = self._enum_value(req, "timeInForce", "GOOD_TILL_DATE")
                req.expirationTimestamp = order.expiry_timestamp_ms
            else:
                req.timeInForce = self._enum_value(req, "timeInForce", "GTC")
            
            # Labels
            if order.label:
                req.label = order.label[:50]
            if order.comment:
                req.comment = order.comment[:100]
            
            print(f"[cTrader] Placing {order.order_type.value} {order.side.value} "
                  f"{order.volume} lots on {order.symbol} @ {order.entry_price}")
            
            from twisted.internet import reactor
            reactor.callFromThread(self._client.send, req)
            
            result = await asyncio.wait_for(future, timeout=30)
            return result
            
        except asyncio.TimeoutError:
            return OrderResult(success=False, message="Order timeout")
        except Exception as e:
            return OrderResult(success=False, message=str(e))
    
    async def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel a pending order"""
        if not self._connected:
            return OrderResult(success=False, message="Not connected")
        
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_requests["order_cancel"] = future
        
        req = ProtoOACancelOrderReq()
        req.ctidTraderAccountId = self.account_id
        req.orderId = int(order_id)
        
        from twisted.internet import reactor
        reactor.callFromThread(self._client.send, req)
        
        try:
            return await asyncio.wait_for(future, timeout=15)
        except asyncio.TimeoutError:
            return OrderResult(success=False, message="Cancel timeout")
    
    async def get_pending_orders(self) -> List[PendingOrder]:
        """Get all pending orders"""
        if not self._connected:
            return []
        
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_requests["reconcile"] = future
        
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self.account_id
        
        from twisted.internet import reactor
        reactor.callFromThread(self._client.send, req)
        
        try:
            await asyncio.wait_for(future, timeout=15)
            return self._pending_orders
        except asyncio.TimeoutError:
            return []
    
    async def get_positions(self) -> List[Position]:
        """Get all open positions"""
        # Uses reconcile which populates both
        await self.get_pending_orders()
        return self._positions


# Synchronous wrapper for CLI usage
class CTraderBrokerSync:
    """Synchronous wrapper for CTraderBroker for use in scripts"""
    
    def __init__(self, broker_id: str, config: dict):
        self.broker = CTraderBroker(broker_id, config)
        self._loop = None
    
    def _get_loop(self):
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
    
    def place_order(self, order: OrderRequest) -> OrderResult:
        return self._get_loop().run_until_complete(self.broker.place_order(order))
    
    def cancel_order(self, order_id: str) -> OrderResult:
        return self._get_loop().run_until_complete(self.broker.cancel_order(order_id))
    
    def get_pending_orders(self) -> List[PendingOrder]:
        return self._get_loop().run_until_complete(self.broker.get_pending_orders())
    
    def get_positions(self) -> List[Position]:
        return self._get_loop().run_until_complete(self.broker.get_positions())
