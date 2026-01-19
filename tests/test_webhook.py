#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test webhook locally by simulating TradingView alerts
Usage: python test_webhook.py [--dry-run]
"""

import argparse
import json
import requests


def send_signal(url: str, signal: dict, token: str = None):
    """Send a signal to the webhook"""
    headers = {"Content-Type": "application/json"}
    
    if token:
        headers["X-Webhook-Token"] = token
    
    try:
        response = requests.post(url, json=signal, headers=headers, timeout=30)
        
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        print(f"❌ Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Test webhook with simulated signals")
    parser.add_argument("--host", default="localhost", help="Webhook host")
    parser.add_argument("--port", type=int, default=5000, help="Webhook port")
    parser.add_argument("--token", default="CHANGE_ME_RANDOM_TOKEN_12345", help="Secret token")
    parser.add_argument("--symbol", default="EURUSD", help="Symbol to test")
    parser.add_argument("--side", default="LONG", choices=["LONG", "SHORT"], help="Trade direction")
    parser.add_argument("--test-only", action="store_true", help="Use /webhook/test endpoint")
    parser.add_argument("--dry-run", action="store_true", help="Print signal without sending")
    
    args = parser.parse_args()
    
    # Build test signal (similar to TradingView JSON output)
    signal = {
        "symbol": args.symbol,
        "side": args.side,
        "order_type": "LIMIT" if args.side == "LONG" else "STOP",
        "entry": 1.0850 if args.symbol == "EURUSD" else 2650.50,
        "sl": 1.0800 if args.symbol == "EURUSD" else 2630.00,
        "tp": 1.0950 if args.symbol == "EURUSD" else 2700.00,
        "validity_bars": 1,
        "atr": 0.0050 if args.symbol == "EURUSD" else 15.00,
        "timeframe": "240"
    }
    
    print("=" * 60)
    print("Webhook Test")
    print("=" * 60)
    print(f"\nSignal to send:")
    print(json.dumps(signal, indent=2))
    
    if args.dry_run:
        print("\n[DRY RUN - Signal not sent]")
        return
    
    endpoint = "/webhook/test" if args.test_only else "/webhook"
    url = f"http://{args.host}:{args.port}{endpoint}"
    
    print(f"\nSending to: {url}")
    print("-" * 60)
    
    success = send_signal(url, signal, args.token)
    
    print("\n" + "=" * 60)
    if success:
        print("✅ Test completed successfully!")
    else:
        print("❌ Test failed!")


if __name__ == "__main__":
    main()
