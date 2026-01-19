#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quick test script for TradeLocker connection
Usage: TL_EMAIL=xxx TL_PASSWORD=xxx TL_SERVER=GFTTL python test_tradelocker.py
"""

import os
import sys
import json
import base64
import requests

# Configuration from environment or defaults
EMAIL = os.environ.get("TL_EMAIL", "")
PASSWORD = os.environ.get("TL_PASSWORD", "")
SERVER = os.environ.get("TL_SERVER", "GFTTL")

AUTH_URL = "https://demo.tradelocker.com/backend-api/auth/jwt/token"


def decode_jwt_payload(token: str) -> dict:
    """Decode JWT payload"""
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
        print(f"⚠️  JWT decode error: {e}")
        return None


def main():
    print("=" * 60)
    print("TradeLocker Connection Test")
    print("=" * 60)
    
    if not EMAIL or not PASSWORD:
        print("❌ Missing environment variables!")
        print("   Required: TL_EMAIL, TL_PASSWORD")
        print("   Optional: TL_SERVER (default: GFTTL)")
        print("\n   Usage:")
        print("   TL_EMAIL=xxx TL_PASSWORD=xxx python test_tradelocker.py")
        sys.exit(1)
    
    print(f"Email: {EMAIL}")
    print(f"Server: {SERVER}")
    print("-" * 60)
    
    # Step 1: Authentication
    print("\n1️⃣  Authenticating...")
    
    payload = {
        "email": EMAIL,
        "password": PASSWORD,
        "server": SERVER
    }
    
    try:
        response = requests.post(AUTH_URL, json=payload, timeout=15)
        
        if response.status_code not in [200, 201]:
            print(f"❌ Authentication failed: {response.status_code}")
            print(f"   Response: {response.text}")
            sys.exit(1)
        
        data = response.json()
        access_token = data.get("accessToken")
        refresh_token = data.get("refreshToken")
        
        print("✅ Authenticated successfully")
        
        # Extract host from JWT
        jwt_payload = decode_jwt_payload(access_token)
        if jwt_payload and 'host' in jwt_payload:
            base_url = f"https://{jwt_payload['host']}"
            print(f"   API Host: {base_url}")
        else:
            base_url = "https://demo.tradelocker.com"
            print(f"   API Host: {base_url} (default)")
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Connection error: {e}")
        sys.exit(1)
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "accept": "application/json"
    }
    
    # Step 2: Get accounts
    print("\n2️⃣  Getting accounts...")
    
    try:
        url = f"{base_url}/backend-api/auth/jwt/all-accounts"
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        accounts = response.json().get('accounts', [])
        
        if not accounts:
            print("❌ No accounts found")
            sys.exit(1)
        
        print(f"📋 Found {len(accounts)} account(s):")
        
        for acc in accounts:
            print(f"   - ID: {acc.get('id')}")
            print(f"     accNum: {acc.get('accNum')}")
            print(f"     Name: {acc.get('name', 'N/A')}")
        
        # Use first account
        account = accounts[0]
        account_id = account.get('id')
        acc_num = account.get('accNum')
        headers["accNum"] = str(acc_num)
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Error getting accounts: {e}")
        sys.exit(1)
    
    # Step 3: Get account state
    print("\n3️⃣  Getting account state...")
    
    try:
        url = f"{base_url}/backend-api/trade/accounts/{account_id}/state"
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        if isinstance(data, dict) and 'd' in data:
            state = data['d']
            
            print(f"\n💰 Account Info:")
            print(f"   Balance: {state.get('balance', 'N/A')}")
            print(f"   Equity: {state.get('equity', 'N/A')}")
            print(f"   Free Margin: {state.get('freeMargin', 'N/A')}")
            print(f"   Used Margin: {state.get('usedMargin', 'N/A')}")
        
    except requests.exceptions.RequestException as e:
        print(f"⚠️  Error getting account state: {e}")
    
    # Step 4: Get instruments
    print("\n4️⃣  Getting instruments...")
    
    try:
        url = f"{base_url}/backend-api/trade/accounts/{account_id}/instruments"
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        instruments = []
        
        if isinstance(data, dict) and 'd' in data:
            instruments_raw = data['d'].get('instruments', [])
            
            for inst in instruments_raw:
                if isinstance(inst, list) and len(inst) >= 2:
                    instruments.append({
                        'id': inst[0],
                        'name': inst[1] if len(inst) > 1 else f"ID:{inst[0]}"
                    })
        
        print(f"📊 Found {len(instruments)} instruments")
        
        # Show first 30
        print("\n   ID         | Symbol Name")
        print("   -----------|-------------------")
        for inst in instruments[:30]:
            print(f"   {str(inst['id']):<10} | {inst['name']}")
        
        if len(instruments) > 30:
            print(f"   ... and {len(instruments) - 30} more")
        
        # Look for common symbols
        print("\n🔍 Common symbols mapping:")
        common = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD", "NAS100", "US30", "SPX500"]
        for inst in instruments:
            name = inst['name'].upper()
            for c in common:
                if c in name:
                    print(f"   {c}: \"{inst['name']}\" (id: {inst['id']})")
        
    except requests.exceptions.RequestException as e:
        print(f"⚠️  Error getting instruments: {e}")
    
    # Step 5: Get pending orders
    print("\n5️⃣  Getting pending orders...")
    
    try:
        url = f"{base_url}/backend-api/trade/accounts/{account_id}/orders"
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        orders = []
        
        if isinstance(data, dict) and 'd' in data:
            orders_raw = data['d'].get('orders', [])
            
            for arr in orders_raw:
                if isinstance(arr, list) and len(arr) > 6:
                    # Filter standalone pending orders
                    if arr[6] == 'New' and (arr[15] is True or arr[16] is None):
                        orders.append({
                            'id': arr[0],
                            'symbol_id': arr[1],
                            'qty': arr[3],
                            'side': arr[4],
                            'type': arr[5],
                            'status': arr[6]
                        })
        
        if orders:
            print(f"📋 Found {len(orders)} pending order(s):")
            for order in orders:
                print(f"   - ID: {str(order['id'])[:16]}...")
                print(f"     Type: {order['type']} {order['side']}")
                print(f"     Qty: {order['qty']}")
        else:
            print("📭 No pending orders")
        
    except requests.exceptions.RequestException as e:
        print(f"⚠️  Error getting orders: {e}")
    
    # Step 6: Get positions
    print("\n6️⃣  Getting open positions...")
    
    try:
        url = f"{base_url}/backend-api/trade/accounts/{account_id}/positions"
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        positions = []
        
        if isinstance(data, dict) and 'd' in data:
            positions_raw = data['d'].get('positions', [])
            
            for arr in positions_raw:
                if isinstance(arr, list) and len(arr) > 7:
                    positions.append({
                        'id': arr[0],
                        'symbol_id': arr[1],
                        'side': arr[3] if len(arr) > 3 else 'N/A',
                        'qty': arr[4] if len(arr) > 4 else 0,
                        'pnl': arr[7] if len(arr) > 7 else 0
                    })
        
        if positions:
            print(f"📋 Found {len(positions)} open position(s):")
            for pos in positions:
                print(f"   - ID: {str(pos['id'])[:16]}...")
                print(f"     Side: {pos['side']}, Qty: {pos['qty']}")
                print(f"     P&L: {pos['pnl']}")
        else:
            print("📭 No open positions")
        
    except requests.exceptions.RequestException as e:
        print(f"⚠️  Error getting positions: {e}")
    
    print("\n" + "=" * 60)
    print("✅ Test completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
