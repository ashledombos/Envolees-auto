#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quick test script for cTrader connection
Reproduces the functionality of ctrader_a_accounts_symbols.py
Usage: CT_CLIENT_ID=xxx CT_CLIENT_SECRET=xxx CT_ACCESS_TOKEN=xxx python test_ctrader.py
"""

import os
import sys
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from twisted.python import log
from twisted.internet import reactor

try:
    from ctrader_open_api import Client, TcpProtocol, EndPoints, Protobuf
    from ctrader_open_api.messages.OpenApiMessages_pb2 import (
        ProtoOAApplicationAuthReq,
        ProtoOAGetAccountListByAccessTokenReq,
        ProtoOAAccountAuthReq,
        ProtoOASymbolsListReq,
        ProtoOATraderReq,
        ProtoOAErrorRes,
    )
except ImportError:
    print("❌ ctrader-open-api not installed. Run: pip install ctrader-open-api")
    sys.exit(1)


def env(name: str, default: str = None) -> str:
    """Get environment variable"""
    v = os.environ.get(name, default)
    if v is None:
        print(f"❌ Missing environment variable: {name}")
        sys.exit(2)
    return v


# Configuration from environment
CLIENT_ID = env("CT_CLIENT_ID")
CLIENT_SECRET = env("CT_CLIENT_SECRET")
ACCESS_TOKEN = env("CT_ACCESS_TOKEN")
ACCOUNT_ID = os.environ.get("CT_ACCOUNT_ID")  # Optional, will be auto-detected

HOST = EndPoints.PROTOBUF_DEMO_HOST
PORT = EndPoints.PROTOBUF_PORT

# State
state = {
    "account_id": int(ACCOUNT_ID) if ACCOUNT_ID else None,
    "symbols_received": False
}

client = Client(HOST, PORT, TcpProtocol)


def stop_later(code: int = 0):
    """Stop reactor properly"""
    def _stop():
        try:
            reactor.stop()
        except Exception:
            pass
        if code != 0:
            raise SystemExit(code)
    reactor.callLater(0, _stop)


def connected(_client):
    """Connection callback"""
    print(f"✅ Connected to {HOST}:{PORT}")
    print("   Authenticating application...")
    
    req = ProtoOAApplicationAuthReq()
    req.clientId = CLIENT_ID
    req.clientSecret = CLIENT_SECRET
    _client.send(req)


def on_message_received(_client, message):
    """Message handler"""
    payload = Protobuf.extract(message)
    ptype = payload.DESCRIPTOR.name
    
    if isinstance(payload, ProtoOAErrorRes):
        print(f"❌ Error: {payload.errorCode} - {payload.description}")
        stop_later(1)
        return
    
    if ptype == "ProtoOAApplicationAuthRes":
        print("✅ Application authenticated")
        
        if state["account_id"]:
            # Account ID provided, authenticate directly
            print(f"   Authenticating account {state['account_id']}...")
            req = ProtoOAAccountAuthReq()
            req.ctidTraderAccountId = state["account_id"]
            req.accessToken = ACCESS_TOKEN
            _client.send(req)
        else:
            # Get account list first
            print("   Getting account list...")
            req = ProtoOAGetAccountListByAccessTokenReq()
            req.accessToken = ACCESS_TOKEN
            _client.send(req)
        return
    
    if ptype == "ProtoOAGetAccountListByAccessTokenRes":
        accounts = list(payload.ctidTraderAccount)
        if not accounts:
            print("❌ No accounts found for this token")
            stop_later(1)
            return
        
        print(f"📋 Found {len(accounts)} account(s):")
        for acc in accounts:
            print(f"   - Account ID: {acc.ctidTraderAccountId}, isLive: {getattr(acc, 'isLive', 'N/A')}")
        
        # Use first account
        state["account_id"] = accounts[0].ctidTraderAccountId
        print(f"   Using account: {state['account_id']}")
        
        req = ProtoOAAccountAuthReq()
        req.ctidTraderAccountId = state["account_id"]
        req.accessToken = ACCESS_TOKEN
        _client.send(req)
        return
    
    if ptype == "ProtoOAAccountAuthRes":
        print(f"✅ Account {state['account_id']} authenticated")
        
        # Get account info
        print("   Getting account info...")
        req = ProtoOATraderReq()
        req.ctidTraderAccountId = state["account_id"]
        _client.send(req)
        return
    
    if ptype == "ProtoOATraderRes":
        trader = payload.trader
        balance = trader.balance / 100  # Convert from cents
        
        print(f"\n💰 Account Info:")
        print(f"   Balance: {balance:.2f}")
        print(f"   Used Margin: {getattr(trader, 'usedMargin', 0) / 100:.2f}")
        print(f"   Leverage: {getattr(trader, 'leverageInCents', 10000) // 100}:1")
        
        # Get symbols
        print("\n   Getting symbols...")
        req = ProtoOASymbolsListReq()
        req.ctidTraderAccountId = state["account_id"]
        _client.send(req)
        return
    
    if ptype == "ProtoOASymbolsListRes":
        symbols = list(payload.symbol)
        print(f"\n📊 Found {len(symbols)} symbols:")
        
        # Show first 30 symbols
        print("\n   ID         | Symbol Name")
        print("   -----------|-------------------")
        for s in symbols[:30]:
            name = getattr(s, "symbolName", "")
            sid = getattr(s, "symbolId", "")
            print(f"   {str(sid):<10} | {name}")
        
        if len(symbols) > 30:
            print(f"   ... and {len(symbols) - 30} more")
        
        # Look for common symbols
        print("\n🔍 Common symbols mapping:")
        common = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD", "NAS100", "US30", "SPX500"]
        for s in symbols:
            name = getattr(s, "symbolName", "")
            for c in common:
                if c in name.upper():
                    print(f"   {c}: symbolId = {s.symbolId}")
        
        print("\n✅ Test completed successfully!")
        stop_later(0)
        return


def watchdog():
    """Timeout watchdog"""
    print("⏰ Timeout: no response received in 30s")
    stop_later(2)


def main():
    print("=" * 60)
    print("cTrader Connection Test")
    print("=" * 60)
    print(f"Client ID: {CLIENT_ID[:8]}...")
    print(f"Host: {HOST}:{PORT}")
    if state["account_id"]:
        print(f"Account ID: {state['account_id']}")
    print("-" * 60)
    
    # Set up timeout
    reactor.callLater(30, watchdog)
    
    client.setConnectedCallback(connected)
    client.setMessageReceivedCallback(on_message_received)
    client.startService()
    reactor.run()


if __name__ == "__main__":
    main()
