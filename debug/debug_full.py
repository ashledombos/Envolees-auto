#!/usr/bin/env python3
"""
Debug complet - À exécuter sur le serveur:
cd ~/dev/envolees-auto && python debug_full.py
"""

import yaml
import sys
from datetime import datetime, timezone

# Charger la config
try:
    with open("config/settings.yaml") as f:
        config = yaml.safe_load(f)
except FileNotFoundError:
    print("❌ config/settings.yaml non trouvé")
    sys.exit(1)

print("=" * 70)
print("CONFIGURATION DES INSTRUMENTS")
print("=" * 70)

instruments = config.get("instruments", {})
for name, inst in instruments.items():
    pip_size = inst.get("pip_size", "NON DÉFINI")
    pip_value = inst.get("pip_value_per_lot", "null (dynamique)")
    quote_curr = inst.get("quote_currency", "USD assumé")
    print(f"{name:12} | pip_size: {pip_size:8} | pip_value: {str(pip_value):20} | quote: {quote_curr}")

print("\n" + "=" * 70)
print("TEST CALCUL POSITION SIZE - USDZAR")
print("=" * 70)

# Simuler le calcul pour USDZAR
usdzar_config = instruments.get("USDZAR", {})
if usdzar_config:
    pip_size = usdzar_config.get("pip_size", 0.0001)
    pip_value_per_lot = usdzar_config.get("pip_value_per_lot")
    quote_currency = usdzar_config.get("quote_currency")
    contract_size = usdzar_config.get("contract_size", 100000)
    
    print(f"Config USDZAR:")
    print(f"  pip_size: {pip_size}")
    print(f"  pip_value_per_lot: {pip_value_per_lot}")
    print(f"  quote_currency: {quote_currency}")
    print(f"  contract_size: {contract_size}")
    
    # Données de l'ordre réel
    entry_price = 16.22713
    sl_price = 16.28703
    account_value = 98503.51
    risk_percent = 0.5
    
    # Calcul
    risk_amount = account_value * (risk_percent / 100)
    sl_distance = abs(entry_price - sl_price)
    sl_pips = sl_distance / pip_size
    
    # Calcul pip value dynamique
    if pip_value_per_lot is not None:
        calculated_pip_value = pip_value_per_lot
    else:
        base_pip_value = contract_size * pip_size
        if quote_currency and quote_currency != "USD":
            # USD/XXX pair - divide by price
            calculated_pip_value = base_pip_value / entry_price
        else:
            calculated_pip_value = base_pip_value
    
    # Calcul lots
    raw_lots = risk_amount / (sl_pips * calculated_pip_value)
    rounded_lots = round(raw_lots * 100) / 100  # Arrondi 0.01
    actual_risk = rounded_lots * sl_pips * calculated_pip_value
    
    print(f"\nCalcul:")
    print(f"  Entry: {entry_price}")
    print(f"  SL: {sl_price}")
    print(f"  SL distance: {sl_distance}")
    print(f"  SL pips: {sl_pips:.1f}")
    print(f"  Risque voulu: ${risk_amount:.2f} ({risk_percent}%)")
    print(f"  Pip value/lot: ${calculated_pip_value:.4f}")
    print(f"  Lots calculés: {raw_lots:.4f} → {rounded_lots:.2f}")
    print(f"  Risque réel: ${actual_risk:.2f} ({actual_risk/account_value*100:.3f}%)")
    
    # Vérification inverse
    print(f"\n  Vérification: 1.33 lots × {sl_pips:.0f} pips × ${calculated_pip_value:.4f} = ${1.33 * sl_pips * calculated_pip_value:.2f}")

else:
    print("❌ USDZAR non configuré dans instruments")

# Test TradeLocker
print("\n" + "=" * 70)
print("TEST CONNEXION TRADELOCKER")
print("=" * 70)

gft_config = config.get("brokers", {}).get("gft_compte2", {})
if gft_config and gft_config.get("enabled", False):
    try:
        from tradelocker import TLAPI
        
        api = TLAPI(
            environment=gft_config.get("base_url", "https://bsb.tradelocker.com"),
            username=gft_config.get("email", ""),
            password=gft_config.get("password", ""),
            server=gft_config.get("server", "")
        )
        
        print("✅ Connexion TradeLocker OK")
        
        # Récupérer les ordres
        orders_df = api.get_all_orders()
        
        if orders_df is None or orders_df.empty:
            print("Aucun ordre pending")
        else:
            print(f"\n{len(orders_df)} ordre(s) trouvé(s)")
            print(f"\nColonnes disponibles: {list(orders_df.columns)}")
            
            for idx, order in orders_df.iterrows():
                print(f"\n--- Ordre {idx} ---")
                for col in orders_df.columns:
                    val = order[col]
                    print(f"  {col}: {val} ({type(val).__name__})")
                    
    except Exception as e:
        print(f"❌ Erreur TradeLocker: {e}")
        import traceback
        traceback.print_exc()
else:
    print("gft_compte2 non configuré ou désactivé")

print("\n" + "=" * 70)
print("VÉRIFICATION VERSION DU CODE")
print("=" * 70)

# Vérifier si le fix du position sizer est présent
try:
    with open("services/position_sizer.py") as f:
        content = f.read()
        if "USD/XXX pairs" in content and "base_pip_value / current_price" in content:
            print("✅ Fix position_sizer v3+ détecté")
        else:
            print("⚠️ Version ancienne du position_sizer - mise à jour nécessaire")
            
    with open("brokers/tradelocker.py") as f:
        content = f.read()
        if "createdAt" in content and "Available fields" in content:
            print("✅ Fix cleaner v4+ détecté")
        else:
            print("⚠️ Version ancienne du tradelocker - mise à jour nécessaire")
except FileNotFoundError as e:
    print(f"❌ Fichier non trouvé: {e}")

# Vérifier le pip_size réel chez le broker
print("\n" + "=" * 70)
print("VÉRIFICATION PIP_SIZE RÉEL CHEZ TRADELOCKER")
print("=" * 70)

if 'api' in dir():
    try:
        instruments_df = api.get_all_instruments()
        if instruments_df is not None and not instruments_df.empty:
            # Chercher USDZAR
            usdzar_rows = instruments_df[instruments_df['name'].str.contains('USDZAR', case=False, na=False)]
            if not usdzar_rows.empty:
                print("\nInstrument USDZAR chez TradeLocker:")
                for col in instruments_df.columns:
                    val = usdzar_rows.iloc[0][col]
                    print(f"  {col}: {val}")
            else:
                print("USDZAR non trouvé, affichage des 5 premiers instruments:")
                for idx, row in instruments_df.head(5).iterrows():
                    print(f"  {row.get('name', 'N/A')}: {dict(row)}")
    except Exception as e:
        print(f"Erreur récupération instruments: {e}")
