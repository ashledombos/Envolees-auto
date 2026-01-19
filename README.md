# Trading Automation System

Système automatisé pour recevoir des alertes TradingView et placer des ordres sur **FTMO (cTrader)** et **Goat Funded Trader (TradeLocker)**.

## 🎯 Fonctionnalités

- ✅ **Réception webhooks TradingView** : Serveur Flask pour recevoir les alertes
- ✅ **Multi-broker** : Support cTrader (FTMO) et TradeLocker (GFT)
- ✅ **Calcul automatique du lot** : Basé sur % de risque du capital
- ✅ **Gestion expiration ordres** : Native (cTrader) ou via cleanup (TradeLocker)
- ✅ **Notifications** : Email, Telegram, Discord
- ✅ **CLI complet** : Tests et gestion en ligne de commande

## 📁 Structure du projet

```
trading-automation/
├── brokers/              # Connecteurs broker
│   ├── base.py          # Classes et interfaces de base
│   ├── ctrader.py       # cTrader Open API
│   └── tradelocker.py   # TradeLocker REST API
├── config/
│   ├── __init__.py      # Gestion de la configuration
│   └── settings.json    # Votre configuration (à créer)
├── services/
│   ├── order_placer.py  # Placement d'ordres
│   └── order_cleaner.py # Nettoyage ordres expirés
├── utils/
│   └── notifications.py # Système de notifications
├── webhook/
│   └── server.py        # Serveur webhook Flask
├── cli/
│   └── main.py          # Interface CLI
├── pine/
│   └── envolees_webhook.pine  # Script TradingView
└── tests/               # Scripts de test
```

## 🚀 Installation rapide

```bash
# 1. Cloner ou extraire le projet
cd trading-automation

# 2. Setup automatique
chmod +x setup.sh
./setup.sh

# 3. Éditer la configuration
nano config/settings.json
```

## ⚙️ Configuration

Copiez `config/settings.example.json` vers `config/settings.json` et remplissez :

### FTMO / cTrader

```json
"ftmo_ctrader": {
  "enabled": true,
  "type": "ctrader",
  "client_id": "votre_client_id",
  "client_secret": "votre_client_secret",
  "access_token": "votre_access_token",
  "account_id": 12345678
}
```

Pour obtenir les credentials cTrader :
1. Connectez-vous sur [Open API](https://openapi.ctrader.com/)
2. Créez une application
3. Obtenez les tokens OAuth

### GFT / TradeLocker

```json
"gft_tradelocker": {
  "enabled": true,
  "type": "tradelocker",
  "email": "votre@email.com",
  "password": "votre_mot_de_passe",
  "server": "GFTTL"
}
```

### Mapping des instruments

Configurez le mapping entre le symbole unifié et les IDs broker :

```json
"instruments_mapping": {
  "EURUSD": 1,           // cTrader: symbolId
  "EURUSD": "EURUSD.X"   // TradeLocker: nom exact
}
```

## 📡 Utilisation

### 1. Tester les connexions broker

```bash
# Tester cTrader
python cli/main.py broker test ftmo_ctrader

# Tester TradeLocker
python cli/main.py broker test gft_tradelocker

# Lister les symboles disponibles
python cli/main.py broker symbols ftmo_ctrader --search EUR
```

### 2. Démarrer le serveur webhook

```bash
# Mode développement
python cli/main.py serve --port 5000

# Mode production avec gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 webhook.server:app
```

### 3. Configurer TradingView

1. Ouvrez l'indicateur Pine Script (`pine/envolees_webhook.pine`)
2. Créez une alerte sur l'indicateur
3. Webhook URL : `http://votre-serveur:5000/webhook?token=VOTRE_TOKEN_SECRET`
4. Le message JSON est généré automatiquement par le script

### 4. Nettoyage des ordres expirés

TradeLocker ne supporte pas l'expiration native des ordres. Configurez un cron :

```bash
# Toutes les 15 minutes
*/15 * * * * cd /path/to/trading-automation && venv/bin/python cli/main.py cleanup
```

Ou manuellement :

```bash
python cli/main.py cleanup
```

## 🖥️ Commandes CLI

```bash
# Configuration
python cli/main.py config show      # Afficher la config
python cli/main.py config validate  # Valider la config

# Brokers
python cli/main.py broker list              # Liste des brokers
python cli/main.py broker test <broker_id>  # Tester connexion
python cli/main.py broker symbols <id>      # Lister symboles
python cli/main.py broker orders <id>       # Ordres en attente
python cli/main.py broker positions <id>    # Positions ouvertes

# Ordres
python cli/main.py order place <broker> <symbol> <side> --entry X --sl Y --tp Z
python cli/main.py order cancel <broker> <order_id>

# Serveur
python cli/main.py serve --port 5000

# Nettoyage
python cli/main.py cleanup
```

## 📝 Format du message TradingView

Le script Pine envoie un JSON comme celui-ci :

```json
{
  "symbol": "EURUSD",
  "side": "LONG",
  "order_type": "LIMIT",
  "entry": 1.0850,
  "sl": 1.0800,
  "tp": 1.0950,
  "validity_bars": 1,
  "atr": 0.0050,
  "timeframe": "240"
}
```

## 🔒 Sécurité

- **Token secret** : Configurez un token aléatoire dans `webhook.secret_token`
- **IP whitelist** : Ajoutez les IPs TradingView dans `webhook.allowed_ips`
- **HTTPS** : Utilisez un reverse proxy (nginx) avec SSL en production

IPs TradingView :
- 52.89.214.238
- 34.212.75.30
- 54.218.53.128
- 52.32.178.7

## 📊 Calcul de la taille de position

```
risk_amount = balance × risk_percent
sl_pips = |entry - sl| / pip_value
lots = risk_amount / (sl_pips × pip_value_per_lot × lot_size)
```

Avec clamp entre `min_lot` et `max_lot` configurés par instrument.

## 🧪 Tests

```bash
# Test connexion cTrader
CT_CLIENT_ID=xxx CT_CLIENT_SECRET=xxx CT_ACCESS_TOKEN=xxx \
  python tests/test_ctrader.py

# Test connexion TradeLocker  
TL_EMAIL=xxx TL_PASSWORD=xxx TL_SERVER=GFTTL \
  python tests/test_tradelocker.py

# Test webhook local
python tests/test_webhook.py --test-only
```

## 📈 Gestion des chandelles 4H (alignée TradingView)

Le système de nettoyage reproduit exactement la logique TradingView :

- **Crypto (24x7)** : Phase 0, chandelles à 00:00, 04:00, 08:00...
- **Forex/Indices (24x5)** : Phase -120, chandelles à 22:00, 02:00, 06:00...
- **Actions US (RTH)** : Phase 150, chandelles à 02:30, 06:30, 10:30...

Les weekends sont exclus pour 24x5 et RTH.

## 🐛 Dépannage

### "Symbol not found"
Vérifiez le mapping dans `instruments_mapping` de chaque broker.

### "Connection timeout" (cTrader)
Le reactor Twisted peut nécessiter plus de temps. Augmentez le timeout.

### "Order failed" (TradeLocker)
Vérifiez que l'instrument est tradable et que les prix sont valides.

### Les ordres ne s'annulent pas
Vérifiez que `created_time` est bien renseigné dans les ordres.

## 📄 Licence

MIT - Utilisation libre pour usage personnel et commercial.

## 👤 Auteur

Développé pour FTMO et Goat Funded Trader prop trading.
