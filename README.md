# Trading Automation System

Système d'automatisation pour exécuter les alertes TradingView sur plusieurs brokers (FTMO/cTrader et GFT/TradeLocker).

## 🎯 Fonctionnalités

- **Webhook server** : Reçoit les alertes TradingView et place les ordres
- **Multi-broker** : Support cTrader (FTMO) et TradeLocker (GFT)
- **Multi-comptes** : Plusieurs comptes par plateforme
- **Filtres pré-placement** : Protection automatique des comptes
  - Marge insuffisante
  - Proche du drawdown limite
  - Trop de positions ouvertes
  - Ordres en doublon
  - Instrument non disponible
- **Délai aléatoire** : Entre les placements pour éviter la détection de copy-trading
- **Position sizing** : Calcul automatique basé sur le risque %
- **Expiration automatique** : Annule les ordres non déclenchés après N bougies
- **Configuration YAML** : Lisible avec commentaires

## 📦 Installation

```bash
# Cloner ou extraire le projet
cd ~/dev/envolees-auto

# Créer l'environnement virtuel et installer
./setup.sh

# Activer l'environnement (à faire à chaque session)
source venv/bin/activate

# Installer PyYAML si pas déjà fait
pip install PyYAML
```

## ⚙️ Configuration

```bash
# Copier l'exemple et éditer
cp config/settings.example.yaml config/settings.yaml
nano config/settings.yaml
```

### Structure du fichier YAML

```yaml
# Paramètres généraux
general:
  risk_percent: 0.5        # Risque par trade
  use_equity: true         # Utiliser l'équité (vs balance)
  order_timeout_candles: 4 # Expiration en bougies
  candle_timeframe_minutes: 240  # H4

# Délai entre brokers (évite détection copy-trading)
execution:
  delay_between_brokers:
    enabled: true
    min_ms: 500
    max_ms: 3000

# Filtres de protection des comptes
filters:
  min_margin_percent: 30
  max_daily_drawdown_percent: 4.0
  max_open_positions: 5
  prevent_duplicate_orders: true

# Brokers
brokers:
  ftmo_ctrader:
    enabled: true
    type: ctrader
    # ... credentials
  
  gft_compte1:
    enabled: true
    type: tradelocker
    base_url: "https://bsb.tradelocker.com"
    # ... credentials

# Mapping instruments centralisé
instruments:
  EURUSD:
    ftmo_ctrader: "EURUSD"
    gft_compte1: "EURUSD.X"
    pip_size: 0.0001
    pip_value_per_lot: 10
```

### cTrader (FTMO)

Les tokens sont rafraîchis et sauvegardés automatiquement.

```yaml
ftmo_ctrader:
  enabled: true
  type: ctrader
  client_id: "..."
  client_secret: "..."
  access_token: "..."
  refresh_token: "..."
  auto_refresh_token: true
  account_id: 12345678
```

### TradeLocker (GFT)

Utilisez `base_url: "https://bsb.tradelocker.com"` pour GFT.

```yaml
gft_compte1:
  enabled: true
  type: tradelocker
  base_url: "https://bsb.tradelocker.com"
  email: "..."
  password: "..."
  server: "GFTTL"
  account_id: 1711519
```

## 🖥️ Commandes CLI

```bash
# Toujours activer le venv d'abord
source venv/bin/activate
```

### Tester les connexions

```bash
python cli/main.py broker test ftmo_ctrader
python cli/main.py broker test gft_compte1
```

### Lister les symboles

```bash
python cli/main.py broker symbols ftmo_ctrader --search EUR
```

### 🧪 Simuler un signal (DRY RUN)

```bash
# Simuler sur tous les brokers
python cli/main.py signal simulate \
  -s EURUSD \
  --side buy \
  -e 1.0850 \
  --sl 1.0800 \
  --tp 1.0950

# Simuler sur un broker spécifique
python cli/main.py signal simulate \
  -s XAUUSD \
  --side sell \
  -e 2650 \
  --sl 2670 \
  -b ftmo_ctrader

# Placer un VRAI ordre (attention!)
python cli/main.py signal simulate \
  -s EURUSD \
  --side buy \
  -e 1.0850 \
  --sl 1.0800 \
  --live
```

### Vérifier les filtres

```bash
python cli/main.py signal check-filters -s EURUSD
```

### Voir les instruments configurés

```bash
python cli/main.py signal list-instruments
```

### Configuration

```bash
python cli/main.py config show
python cli/main.py config validate
```

## 🌐 Webhook Server

```bash
# Démarrer
python cli/main.py serve --port 5000

# URL webhook pour TradingView
http://votre-serveur:5000/webhook?token=VOTRE_TOKEN_SECRET
```

### Format des alertes TradingView

```json
{
  "symbol": "{{ticker}}",
  "side": "{{strategy.order.action}}",
  "entry": {{strategy.order.price}},
  "sl": {{plot("SL")}},
  "tp": {{plot("TP")}},
  "timeframe": "240"
}
```

## 🛡️ Filtres de Protection

Avant chaque placement, le système vérifie :

| Filtre | Description |
|--------|-------------|
| Instrument disponible | Le symbole existe sur ce broker |
| Marge suffisante | Marge libre > seuil configuré |
| Drawdown | Pas trop proche de la limite |
| Positions max | Pas trop de positions ouvertes |
| Ordres pending max | Pas trop d'ordres en attente |
| Pas de doublon | Pas d'ordre pending sur le même instrument |

Si un filtre échoue, l'ordre est **skippé** pour ce broker (pas d'erreur).

## 📊 Position Sizing

Le calcul de taille de lot est automatique :

```
Lots = (Équité × Risque%) / (SL_pips × Valeur_pip_par_lot)
```

Pour les paires cross (ex: EURJPY), configurez `quote_currency` dans les instruments.

## 📁 Structure

```
trading-automation/
├── brokers/           # Connecteurs cTrader & TradeLocker
├── cli/               # Interface ligne de commande
├── config/
│   ├── settings.yaml  # Votre config (gitignored)
│   └── settings.example.yaml
├── services/
│   ├── order_placer.py    # Placement avec filtres
│   └── position_sizer.py  # Calcul taille de lot
├── webhook/           # Serveur Flask
└── requirements.txt
```

## 🔧 Troubleshooting

### "PyYAML not installed"
```bash
pip install PyYAML
```

### "Broker not connected"
Vérifiez le `base_url` pour GFT : `https://bsb.tradelocker.com`

### "Token refresh error"
Régénérez un nouveau couple access/refresh token sur openapi.ctrader.com

### "0 instruments"
Pour TradeLocker, utilisez le bon host (`bsb.tradelocker.com` pour GFT)

## 📝 Notes

- Les tokens cTrader sont rafraîchis automatiquement (validité ~30 jours)
- Le fichier `settings.yaml` contient vos credentials - **jamais commiter**
- Testez toujours avec `--dry-run` avant `--live`
- Le délai aléatoire entre brokers aide à éviter la détection de copy-trading

## 📄 License

Usage personnel uniquement.
