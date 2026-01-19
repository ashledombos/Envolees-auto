#!/bin/bash
# Trading Automation Quick Setup Script

set -e

echo "=============================================="
echo "Trading Automation System - Quick Setup"
echo "=============================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✅ Python $PYTHON_VERSION found"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo ""
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "✅ Virtual environment created"
fi

# Activate virtual environment
source venv/bin/activate
echo "✅ Virtual environment activated"

# Install dependencies
echo ""
echo "Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "✅ Dependencies installed"

# Create config if it doesn't exist
if [ ! -f "config/settings.json" ]; then
    echo ""
    echo "Creating configuration file..."
    cp config/settings.example.json config/settings.json
    echo "✅ Configuration file created at config/settings.json"
    echo "   ⚠️  Please edit this file with your broker credentials!"
fi

# Test imports
echo ""
echo "Testing imports..."
python3 -c "
import sys
try:
    from config import load_config
    from brokers import create_all_brokers
    from services import OrderPlacer
    print('✅ All modules imported successfully')
except ImportError as e:
    print(f'❌ Import error: {e}')
    sys.exit(1)
"

echo ""
echo "=============================================="
echo "Setup Complete!"
echo "=============================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Edit config/settings.json with your broker credentials:"
echo "   - FTMO/cTrader: client_id, client_secret, access_token, account_id"
echo "   - GFT/TradeLocker: email, password"
echo ""
echo "2. Test broker connections:"
echo "   python cli/main.py broker test ftmo_ctrader"
echo "   python cli/main.py broker test gft_tradelocker"
echo ""
echo "3. Start the webhook server:"
echo "   python cli/main.py serve --port 5000"
echo ""
echo "4. Set up TradingView alerts with webhook URL:"
echo "   http://your-server:5000/webhook?token=YOUR_SECRET"
echo ""
echo "5. (Optional) Set up cron for order cleanup:"
echo "   */15 * * * * cd $SCRIPT_DIR && venv/bin/python cli/main.py cleanup"
echo ""
