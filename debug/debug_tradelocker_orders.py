#!/usr/bin/env python3
"""Debug script to see TradeLocker order fields"""

# À exécuter sur le serveur avec:
# cd ~/dev/envolees-auto && python debug_tradelocker_orders.py

from tradelocker import TLAPI
import yaml
import pandas as pd

# Charger la config
with open("config/settings.yaml") as f:
    config = yaml.safe_load(f)

# Prendre le premier compte GFT
gft_config = config["brokers"]["gft_compte2"]

api = TLAPI(
    environment=gft_config["environment"],
    username=gft_config["email"],
    password=gft_config["password"],
    server=gft_config["server"]
)

print("=" * 60)
print("TradeLocker Order Fields Debug")
print("=" * 60)

# Récupérer les ordres
orders_df = api.get_all_orders()

if orders_df is None or orders_df.empty:
    print("No pending orders found")
else:
    print(f"\nFound {len(orders_df)} order(s)")
    print(f"\nAvailable columns: {list(orders_df.columns)}")
    
    print("\n" + "=" * 60)
    print("Order details:")
    print("=" * 60)
    
    for idx, order in orders_df.iterrows():
        print(f"\n--- Order {idx} ---")
        for col in orders_df.columns:
            val = order[col]
            print(f"  {col}: {val} (type: {type(val).__name__})")
