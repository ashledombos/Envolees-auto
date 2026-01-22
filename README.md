# Envolées Auto - Trading Automation System

Système d'automatisation de trading FVG pour prop firms (FTMO, GFT).

## Version

Voir le fichier `VERSION` pour la version actuelle.

```bash
cat VERSION
# ou
python cli/main.py --version
```

## Structure des fichiers de configuration

La configuration est divisée en 3 fichiers pour plus de sécurité:

```
config/
├── settings.yaml        # Paramètres généraux (peut être commité)
├── secrets.yaml         # Credentials brokers (NE PAS COMMITER)
└── instruments.yaml     # Configuration des instruments (optionnel)
```

### settings.yaml
- Paramètres de risque, filtres, webhook
- Configuration des brokers (sans credentials)

### secrets.yaml
- Token webhook
- Client ID/Secret cTrader
- Email/Password TradeLocker

### instruments.yaml (optionnel)
- Mapping des symboles par broker
- pip_size, pip_value_per_lot, quote_currency

## Installation

```bash
# Cloner le dépôt
git clone <repo> envolees-auto
cd envolees-auto

# Créer l'environnement virtuel
python3 -m venv venv
source venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt

# Copier les fichiers de configuration
cp config/settings.example.yaml config/settings.yaml
cp config/secrets.example.yaml config/secrets.yaml
cp config/instruments.example.yaml config/instruments.yaml

# Éditer les fichiers
nano config/secrets.yaml  # Ajouter vos credentials
nano config/settings.yaml # Personnaliser si besoin
```

## Services Systemd

```bash
# Copier les services (utilisateur)
cp systemd/*.service ~/.config/systemd/user/

# Activer le linger (survie après logout)
sudo loginctl enable-linger $USER

# Recharger et activer
systemctl --user daemon-reload
systemctl --user enable envolees-webhook envolees-cleaner envolees-monitor
systemctl --user start envolees-webhook envolees-cleaner

# Vérifier le statut
systemctl --user status envolees-webhook envolees-cleaner
```

## Commandes CLI

```bash
# Version
python cli/main.py version

# Afficher la config
python cli/main.py config show

# Vérifier les ordres pending avec analyse du risque
python cli/main.py order check

# Lister les symboles d'un broker
python cli/main.py broker symbols ftmo_ctrader

# Simuler un signal
python cli/main.py signal simulate -s EURUSD --side buy -e 1.04 --sl 1.035

# Démarrer le serveur webhook
python cli/main.py serve --port 5000

# Démarrer le cleaner d'ordres
python cli/main.py cleaner start --interval 60

# Health check
python cli/monitor.py check
```

## Monitoring

Le script `cli/monitor.py` surveille le système:

```bash
# Vérification unique
python cli/monitor.py check

# Surveillance continue (toutes les 5 min)
python cli/monitor.py watch --interval 300

# Avec alertes (nécessite apprise)
pip install apprise
python cli/monitor.py watch --alert-channel "tgram://BOT_TOKEN/CHAT_ID"
```

## Structure du projet

```
envolees-auto/
├── VERSION                 # Numéro de version
├── cli/
│   ├── main.py            # CLI principal
│   └── monitor.py         # Health monitor
├── brokers/
│   ├── ctrader.py         # Connecteur cTrader (FTMO)
│   └── tradelocker.py     # Connecteur TradeLocker (GFT)
├── config/
│   ├── __init__.py        # Loader de config
│   ├── settings.yaml      # Config principale
│   ├── secrets.yaml       # Credentials (gitignore)
│   └── instruments.yaml   # Mapping instruments
├── services/
│   ├── order_placer.py    # Placement d'ordres
│   ├── position_sizer.py  # Calcul des lots
│   └── order_cleaner.py   # Nettoyage ordres expirés
├── webhook/
│   └── server.py          # Serveur Flask webhook
├── logs/                   # Fichiers de log
├── systemd/               # Services systemd
└── debug/                 # Scripts de debug
```

## Calcul du Position Sizing

Le système calcule automatiquement la taille de position:

```
lots = risk_amount / (sl_pips × pip_value_per_lot)
```

### Types de paires

1. **XXX/USD** (EURUSD, GBPUSD): `pip_value = 10` (fixe)
2. **USD/XXX** (USDZAR, USDMXN): `pip_value = 10 / prix`
3. **XXX/JPY** (EURJPY, AUDJPY): `pip_value = 1000 / prix`

### Configuration des instruments

```yaml
# Paire XXX/USD - pip value fixe
EURUSD:
  pip_size: 0.0001
  pip_value_per_lot: 10

# Paire USD/XXX - pip value dynamique
USDZAR:
  pip_size: 0.0001
  pip_value_per_lot: null  # Important!
  quote_currency: "ZAR"    # Important!
```

## Webhook TradingView

Endpoint: `POST /webhook?token=VOTRE_TOKEN`

```json
{
  "symbol": "EURUSD",
  "side": "buy",
  "entry": 1.0400,
  "sl": 1.0350,
  "tp": 1.0500
}
```

## Changelog

### v5.1.0
- Configuration séparée en 3 fichiers (settings, secrets, instruments)
- Commande `order check` pour vérifier le risque des ordres pending
- Commande `version` pour afficher la version
- Script de monitoring avec alertes
- Fix asyncio (event loop already running)
- Fix cleaner TradeLocker (champ createdDate)
- Services systemd inclus

### v5.0.0
- Fix calcul pip_value pour paires USD/XXX
- Logs de debug pour position sizing

### v4.0.0
- Fix cleaner TradeLocker
- Debug script complet

### v3.0.0
- Réponse asynchrone webhook (HTTP 202)
- Système de logging avec rotation
- Service cleaner systemd
