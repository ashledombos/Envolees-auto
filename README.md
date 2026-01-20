# Trading Automation System

Système d'automatisation pour exécuter les alertes TradingView sur plusieurs brokers (FTMO/cTrader et GFT/TradeLocker).

## 🎯 Fonctionnalités

- **Webhook server** : Reçoit les alertes TradingView et place les ordres
- **Multi-broker** : Support cTrader (FTMO) et TradeLocker (Goat Funded Trader)
- **Ordres limites** : Place des ordres avec SL/TP basés sur les FVG
- **Expiration automatique** : Annule les ordres non déclenchés après N bougies
- **Gestion du risque** : Calcul automatique de la taille de position (% du capital)
- **Notifications** : Alertes optionnelles (Telegram, Discord, Email...)
- **CLI complète** : Gestion des brokers, ordres, et configuration

## 📦 Installation

```bash
# Cloner ou extraire le projet
cd ~/dev/envolees-auto

# Créer l'environnement virtuel et installer les dépendances
./setup.sh

# Activer l'environnement (à faire à chaque session)
source venv/bin/activate
```

### Dépendances système

- Python 3.10+
- pip

## ⚙️ Configuration

Copier et éditer le fichier de configuration :

```bash
cp config/settings.example.json config/settings.json
nano config/settings.json
```

### Configuration cTrader (FTMO)

```json
"ftmo_ctrader": {
  "enabled": true,
  "type": "ctrader",
  "name": "FTMO cTrader",
  "is_demo": true,
  "client_id": "YOUR_CLIENT_ID",
  "client_secret": "YOUR_CLIENT_SECRET",
  "access_token": "YOUR_ACCESS_TOKEN",
  "refresh_token": "YOUR_REFRESH_TOKEN",
  "auto_refresh_token": true,
  "account_id": 12345678,
  "instruments_mapping": {}
}
```

#### Obtenir les credentials cTrader

1. Aller sur [OpenAPI cTrader](https://openapi.ctrader.com/)
2. Créer une application
3. Générer un access_token et refresh_token via OAuth2
4. Le système rafraîchit automatiquement les tokens (validité ~30 jours)

> **Note** : Les tokens sont sauvegardés automatiquement dans `settings.json` après chaque refresh.

### Configuration TradeLocker (GFT)

```json
"gft_tradelocker": {
  "enabled": true,
  "type": "tradelocker",
  "name": "Goat Funded Trader",
  "is_demo": true,
  "email": "your@email.com",
  "password": "your_password",
  "server": "GFTTL",
  "account_id": null,
  "instruments_mapping": {}
}
```

> **Note** : Si vous avez plusieurs comptes, lancez `broker test` pour voir la liste des IDs, puis configurez `account_id` avec l'ID du compte actif souhaité.

### Configuration générale

```json
"general": {
  "risk_percent": 0.5,
  "default_rr_ratio": 2.5,
  "order_timeout_candles": 4,
  "candle_timeframe_minutes": 240
}
```

| Paramètre | Description |
|-----------|-------------|
| `risk_percent` | Risque par trade (% du capital) |
| `default_rr_ratio` | Ratio Risk/Reward par défaut |
| `order_timeout_candles` | Nombre de bougies avant expiration |
| `candle_timeframe_minutes` | Timeframe en minutes (240 = H4) |

## 🖥️ Utilisation CLI

Toujours activer le venv avant utilisation :

```bash
source venv/bin/activate
```

### Tester les connexions

```bash
# Tester cTrader
python cli/main.py broker test ftmo_ctrader

# Tester TradeLocker
python cli/main.py broker test gft_tradelocker
```

### Lister les symboles

```bash
# Tous les symboles
python cli/main.py broker symbols ftmo_ctrader

# Rechercher
python cli/main.py broker symbols ftmo_ctrader --search EUR
python cli/main.py broker symbols ftmo_ctrader --search GOLD
```

### Voir les positions et ordres

```bash
# Positions ouvertes
python cli/main.py broker positions ftmo_ctrader

# Ordres pending
python cli/main.py broker orders ftmo_ctrader
```

### Configuration

```bash
# Voir la configuration actuelle
python cli/main.py config show

# Modifier un paramètre
python cli/main.py config set general.risk_percent 0.5
```

## 🌐 Webhook Server

### Démarrer le serveur

```bash
# Mode développement
python cli/main.py serve --port 5000

# Mode production (avec gunicorn)
source venv/bin/activate
gunicorn -w 2 -b 0.0.0.0:5000 webhook.server:app
```

### Endpoints

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/webhook` | POST | Recevoir les alertes TradingView |
| `/webhook/test` | POST | Tester le parsing d'une alerte |
| `/health` | GET | Health check |
| `/status` | GET | Statut du système |

### Sécurité

Configurer un token secret dans `settings.json` :

```json
"webhook": {
  "secret_token": "YOUR_SECRET_TOKEN",
  "allowed_ips": []
}
```

URL du webhook : `http://your-server:5000/webhook?token=YOUR_SECRET_TOKEN`

## 📊 Format des Alertes TradingView

### Format JSON (recommandé)

```json
{
  "symbol": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "price": {{strategy.order.price}},
  "sl": {{plot("SL")}},
  "tp": {{plot("TP")}},
  "fvg_top": {{plot("FVG_TOP")}},
  "fvg_bottom": {{plot("FVG_BOTTOM")}},
  "timeframe": "240",
  "strategy": "envolees"
}
```

### Champs

| Champ | Description | Exemple |
|-------|-------------|---------|
| `symbol` | Symbole de l'instrument | `EURUSD`, `XAUUSD` |
| `action` | Direction | `buy` ou `sell` |
| `price` | Prix d'entrée (ordre limite) | `1.0850` |
| `sl` | Stop Loss | `1.0800` |
| `tp` | Take Profit | `1.0950` |
| `fvg_top` | Haut du FVG | `1.0860` |
| `fvg_bottom` | Bas du FVG | `1.0840` |

## 📁 Structure du Projet

```
trading-automation/
├── brokers/
│   ├── base.py           # Classes de base
│   ├── ctrader.py        # Connecteur cTrader (FTMO)
│   └── tradelocker.py    # Connecteur TradeLocker (GFT)
├── cli/
│   └── main.py           # Interface ligne de commande
├── config/
│   ├── __init__.py       # Chargement de la configuration
│   ├── settings.json     # Configuration (créé par vous)
│   └── settings.example.json
├── pine/
│   └── envolees_webhook.pine  # Script Pine avec alertes
├── services/
│   ├── order_placer.py   # Logique de placement d'ordres
│   └── order_cleaner.py  # Nettoyage des ordres expirés
├── tests/
│   ├── test_ctrader.py
│   ├── test_tradelocker.py
│   └── test_webhook.py
├── utils/
│   └── notifications.py  # Système de notifications
├── webhook/
│   └── server.py         # Serveur Flask
├── requirements.txt
├── setup.sh
└── README.md
```

## 🚀 Déploiement Production

### Avec systemd

Créer `/etc/systemd/system/trading-webhook.service` :

```ini
[Unit]
Description=Trading Webhook Server
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/home/your_user/dev/envolees-auto
Environment=PATH=/home/your_user/dev/envolees-auto/venv/bin
ExecStart=/home/your_user/dev/envolees-auto/venv/bin/gunicorn -w 2 -b 0.0.0.0:5000 webhook.server:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable trading-webhook
sudo systemctl start trading-webhook
sudo systemctl status trading-webhook
```

### Nettoyage automatique des ordres (cron)

```bash
crontab -e
```

Ajouter :
```
*/15 * * * * cd /home/your_user/dev/envolees-auto && venv/bin/python cli/main.py cleanup
```

## 🔧 Troubleshooting

### "pydantic import error"

Vous n'avez pas activé le venv :
```bash
source venv/bin/activate
```

### "Token refresh error"

Le refresh_token est à usage unique. Si vous avez utilisé un ancien token :
1. Régénérez un nouveau couple access_token/refresh_token sur openapi.ctrader.com
2. Mettez à jour `settings.json`

### "Cannot set account_id to None"

Le `account_id` n'est pas configuré. Lancez `broker test` pour voir vos comptes et ajoutez l'ID dans la config.

### TradeLocker "0 instruments"

Vérifiez que vous utilisez le bon `account_id` (compte actif). Lancez `broker test` pour voir la liste des comptes.

### Ordres non placés

1. Vérifiez les logs du webhook server
2. Vérifiez que le symbole existe : `broker symbols <broker> --search SYMBOL`
3. Vérifiez le mapping dans `instruments_mapping` si les noms diffèrent

## 📝 Notes

- Les tokens cTrader expirent après ~30 jours mais sont rafraîchis automatiquement
- Le refresh_token cTrader est à **usage unique** - il est sauvegardé automatiquement après chaque refresh
- Testez toujours en démo avant de passer en live
- Les fichiers `config/settings.json` contiennent des credentials sensibles - ne les commitez jamais

## 📄 License

Usage personnel uniquement.
