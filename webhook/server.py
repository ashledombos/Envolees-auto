#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Webhook server for receiving TradingView alerts
"""

import os
import sys
import json
import asyncio
import threading
import logging
import time
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from typing import Optional
from functools import wraps

from flask import Flask, request, jsonify, abort
from queue import Queue, Empty
import random

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import load_config, get_config
from services.order_placer import OrderPlacer, SignalData
from utils.notifications import get_notification_service, NotificationType, Notification


# =============================================================================
# SIGNAL QUEUE CONFIGURATION
# =============================================================================
# Signals are queued and processed sequentially to avoid overwhelming brokers
# when multiple alerts arrive simultaneously

_signal_queue: Queue = Queue()
_queue_worker_started = False
_queue_worker_lock = threading.Lock()


def start_queue_worker():
    """Start the background worker that processes signals from the queue"""
    global _queue_worker_started
    
    with _queue_worker_lock:
        if _queue_worker_started:
            return
        _queue_worker_started = True
    
    def worker():
        """Background worker that processes signals sequentially"""
        config = get_config()
        
        # Get delay settings (reuse delay_between_brokers config, or default 1-3s)
        delay_config = config.execution.delay_between_brokers
        min_delay_ms = delay_config.min_ms if delay_config.enabled else 1000
        max_delay_ms = delay_config.max_ms if delay_config.enabled else 3000
        
        logging.info(f"[QueueWorker] Started - delay between signals: {min_delay_ms}-{max_delay_ms}ms")
        
        last_signal_time = 0
        
        while True:
            try:
                # Wait for next signal (blocking)
                item = _signal_queue.get(timeout=60)
                
                if item is None:
                    continue
                
                request_id, signal, brokers = item
                
                # Apply delay since last signal (if not the first one)
                if last_signal_time > 0:
                    elapsed_ms = (time.time() - last_signal_time) * 1000
                    required_delay_ms = random.randint(min_delay_ms, max_delay_ms)
                    
                    if elapsed_ms < required_delay_ms:
                        wait_ms = required_delay_ms - elapsed_ms
                        logging.info(f"[QueueWorker] Waiting {int(wait_ms)}ms before next signal...")
                        time.sleep(wait_ms / 1000)
                
                # Process the signal
                logging.info(f"[QueueWorker] [{request_id}] Processing {signal.symbol} {signal.side}")
                
                try:
                    placer = get_order_placer()
                    
                    # Create event loop for this operation
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    try:
                        results = loop.run_until_complete(placer.place_signal(signal, brokers))
                    finally:
                        loop.close()
                    
                    # Log results
                    success_count = sum(1 for r in results.values() if r.success)
                    total_count = len(results)
                    
                    logging.info(f"[QueueWorker] [{request_id}] Completed: {success_count}/{total_count} successful")
                    
                    for broker_id, result in results.items():
                        if result.success:
                            order_id = result.order_result.order_id if result.order_result else "N/A"
                            logging.info(f"[QueueWorker] [{request_id}] ✅ {broker_id}: Order {order_id}")
                        else:
                            error = result.order_result.message if result.order_result else result.error
                            logging.warning(f"[QueueWorker] [{request_id}] ❌ {broker_id}: {error}")
                    
                except Exception as e:
                    logging.error(f"[QueueWorker] [{request_id}] Error: {e}", exc_info=True)
                
                finally:
                    last_signal_time = time.time()
                    _signal_queue.task_done()
                
            except Empty:
                # No signal in queue, continue waiting
                continue
            except Exception as e:
                logging.error(f"[QueueWorker] Unexpected error: {e}", exc_info=True)
    
    thread = threading.Thread(target=worker, daemon=True, name="SignalQueueWorker")
    thread.start()
    logging.info("[QueueWorker] Background worker thread started")


def queue_signal(request_id: str, signal: SignalData, brokers: list = None):
    """Add a signal to the processing queue"""
    queue_size = _signal_queue.qsize()
    _signal_queue.put((request_id, signal, brokers))
    logging.info(f"[QueueWorker] [{request_id}] Signal queued ({signal.symbol} {signal.side}) - Queue size: {queue_size + 1}")


# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

def setup_logging(log_dir: str = None):
    """Configure logging to file and console"""
    if log_dir is None:
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    
    os.makedirs(log_dir, exist_ok=True)
    
    # Main log file (all messages)
    main_handler = RotatingFileHandler(
        os.path.join(log_dir, "envolees.log"),
        maxBytes=10*1024*1024,  # 10 MB
        backupCount=5
    )
    main_handler.setLevel(logging.INFO)
    main_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    
    # Error log file (errors only)
    error_handler = RotatingFileHandler(
        os.path.join(log_dir, "errors.log"),
        maxBytes=5*1024*1024,  # 5 MB
        backupCount=3
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s\n%(pathname)s:%(lineno)d',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    
    # Orders log file (order-specific events)
    orders_handler = RotatingFileHandler(
        os.path.join(log_dir, "orders.log"),
        maxBytes=10*1024*1024,  # 10 MB
        backupCount=10
    )
    orders_handler.setLevel(logging.INFO)
    orders_handler.setFormatter(logging.Formatter(
        '%(asctime)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    ))
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(main_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)
    
    # Orders logger (separate)
    orders_logger = logging.getLogger('orders')
    orders_logger.addHandler(orders_handler)
    orders_logger.propagate = False  # Don't duplicate to main log
    
    # Reduce noise from libraries
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('tradelocker').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    return log_dir


# Initialize logging
LOG_DIR = setup_logging()


app = Flask(__name__)

# Configure Flask logging
app.logger.handlers = []  # Remove default handlers
app.logger.addHandler(logging.getLogger().handlers[0])  # Use our handlers
app.logger.setLevel(logging.INFO)

# Global order placer instance
_order_placer: Optional[OrderPlacer] = None
_order_placer_lock = threading.Lock()
_event_loop: Optional[asyncio.AbstractEventLoop] = None


def get_order_placer() -> OrderPlacer:
    """Get or create the global OrderPlacer instance"""
    global _order_placer, _event_loop
    
    with _order_placer_lock:
        if _order_placer is None:
            config = get_config()
            _order_placer = OrderPlacer(config)
            
            # Create event loop for async operations
            _event_loop = asyncio.new_event_loop()
            
            # Connect in background
            def connect():
                asyncio.set_event_loop(_event_loop)
                _event_loop.run_until_complete(_order_placer.connect())
            
            thread = threading.Thread(target=connect, daemon=True)
            thread.start()
            thread.join(timeout=30)
        
        return _order_placer


def require_auth(f):
    """Decorator to require authentication via secret token"""
    @wraps(f)
    def decorated(*args, **kwargs):
        config = get_config()
        expected_token = config.webhook.secret_token
        
        if expected_token == "CHANGE_ME":
            # No auth configured, allow all
            return f(*args, **kwargs)
        
        # Check Authorization header
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if token == expected_token:
                return f(*args, **kwargs)
        
        # Check X-Webhook-Token header
        token_header = request.headers.get("X-Webhook-Token", "")
        if token_header == expected_token:
            return f(*args, **kwargs)
        
        # Check query parameter
        token_param = request.args.get("token", "")
        if token_param == expected_token:
            return f(*args, **kwargs)
        
        # Check in JSON body
        if request.is_json:
            data = request.get_json(silent=True) or {}
            body_token = data.get("token", data.get("secret", ""))
            if body_token == expected_token:
                return f(*args, **kwargs)
        
        app.logger.warning(f"Unauthorized request from {request.remote_addr}")
        abort(401, description="Unauthorized")
    
    return decorated


def check_ip_allowed():
    """Check if request IP is allowed"""
    config = get_config()
    allowed_ips = config.webhook.allowed_ips
    
    if not allowed_ips:
        return True
    
    client_ip = request.remote_addr
    
    # Also check X-Forwarded-For for proxied requests
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    
    if client_ip in allowed_ips:
        return True
    
    # Check for TradingView IPs
    tradingview_ips = [
        "52.89.214.238",
        "34.212.75.30",
        "54.218.53.128",
        "52.32.178.7"
    ]
    
    if client_ip in tradingview_ips:
        return True
    
    return False


@app.before_request
def before_request():
    """Check IP whitelist before processing request"""
    if not check_ip_allowed():
        app.logger.warning(f"Request from non-allowed IP: {request.remote_addr}")
        abort(403, description="Forbidden")


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


@app.route("/webhook", methods=["POST"])
@require_auth
def webhook():
    """
    Main webhook endpoint for TradingView alerts.
    
    Expected JSON payload:
    {
        "symbol": "EURUSD",
        "side": "LONG",      // or "SHORT", "BUY", "SELL"
        "entry": 1.0850,
        "sl": 1.0800,
        "tp": 1.0950,
        "order_type": "LIMIT",  // optional: LIMIT, STOP, MARKET
        "validity_bars": 1,     // optional
        "atr": 0.0050,          // optional
        "timeframe": "H4",      // optional
        "brokers": ["ftmo_ctrader", "gft_tradelocker"]  // optional: specific brokers
    }
    
    TradingView alert message format (to parse):
    🟢 LONG EURUSD (H4)
    Entry: 1.0850
    SL: 1.0800
    TP: 1.0950
    ...
    """
    try:
        # Parse request
        if request.is_json:
            data = request.get_json()
        else:
            # Try to parse text message (TradingView format)
            text = request.get_data(as_text=True)
            data = parse_tradingview_alert(text)
        
        app.logger.info(f"Received webhook: {json.dumps(data, default=str)}")
        
        # Validate required fields
        required_fields = ["symbol", "side", "entry", "sl", "tp"]
        for field in required_fields:
            alt_field = {"entry": "entry_price", "sl": "stop_loss", "tp": "take_profit"}.get(field)
            if field not in data and (alt_field is None or alt_field not in data):
                return jsonify({
                    "success": False,
                    "error": f"Missing required field: {field}"
                }), 400
        
        # Create signal
        signal = SignalData.from_webhook(data)
        
        # Get target brokers
        brokers = data.get("brokers")
        if isinstance(brokers, str):
            brokers = [brokers]
        
        # Generate request ID for tracking
        request_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")[:18]
        
        # Queue the signal for sequential processing
        queue_signal(request_id, signal, brokers)
        
        # Respond immediately to TradingView
        queue_size = _signal_queue.qsize()
        response = {
            "success": True,
            "status": "queued",
            "request_id": request_id,
            "queue_position": queue_size,
            "signal": {
                "symbol": signal.symbol,
                "side": signal.side,
                "entry": signal.entry_price,
                "sl": signal.stop_loss,
                "tp": signal.take_profit,
                "rr_ratio": round(signal.calculate_rr_ratio(), 2)
            },
            "message": f"Signal queued for processing (position: {queue_size})",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        app.logger.info(f"[{request_id}] Signal queued: {signal.symbol} {signal.side} (queue: {queue_size})")
        
        return jsonify(response), 202  # 202 Accepted
        
    except Exception as e:
        app.logger.error(f"Webhook error: {e}", exc_info=True)
        
        # Send error notification
        notification_service = get_notification_service()
        notification_service.notify_error(
            broker="webhook",
            message=f"Error processing webhook: {str(e)}"
        )
        
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


def parse_tradingview_alert(text: str) -> dict:
    """
    Parse TradingView alert text message into structured data.
    
    Expected format:
    🟢 LONG EURUSD (H4)
    Entry: 1.0850
    SL: 1.0800
    TP: 1.0950
    Validité: 1 barre(s)
    ATR: 0.0050
    EMA200: 1.0750
    """
    data = {}
    lines = text.strip().split("\n")
    
    for line in lines:
        line = line.strip()
        
        # First line: direction and symbol
        if "LONG" in line.upper() or "🟢" in line:
            data["side"] = "LONG"
            # Extract symbol - look for word after LONG
            parts = line.replace("🟢", "").replace("🔴", "").split()
            for i, part in enumerate(parts):
                if part.upper() == "LONG" and i + 1 < len(parts):
                    data["symbol"] = parts[i + 1].replace("(", "").replace(")", "")
                    break
        elif "SHORT" in line.upper() or "🔴" in line:
            data["side"] = "SHORT"
            parts = line.replace("🟢", "").replace("🔴", "").split()
            for i, part in enumerate(parts):
                if part.upper() == "SHORT" and i + 1 < len(parts):
                    data["symbol"] = parts[i + 1].replace("(", "").replace(")", "")
                    break
        
        # Parse key: value lines
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            
            # Remove any trailing text after the number
            value_parts = value.split()
            if value_parts:
                value = value_parts[0]
            
            try:
                if key in ["entry", "entry price", "entrée"]:
                    data["entry"] = float(value)
                elif key in ["sl", "stop loss", "stoploss"]:
                    data["sl"] = float(value)
                elif key in ["tp", "take profit", "takeprofit"]:
                    data["tp"] = float(value)
                elif key in ["atr"]:
                    data["atr"] = float(value)
                elif key in ["validité", "validity", "validbars", "valid bars"]:
                    data["validity_bars"] = int(value.split()[0])
            except (ValueError, IndexError):
                pass
    
    return data


@app.route("/webhook/test", methods=["POST", "GET"])
def webhook_test():
    """Test endpoint that doesn't place real orders"""
    if request.method == "GET":
        return jsonify({
            "message": "Webhook test endpoint ready",
            "usage": "POST JSON to this endpoint to test parsing"
        })
    
    try:
        if request.is_json:
            data = request.get_json()
        else:
            text = request.get_data(as_text=True)
            data = parse_tradingview_alert(text)
        
        signal = SignalData.from_webhook(data)
        
        return jsonify({
            "success": True,
            "parsed": {
                "symbol": signal.symbol,
                "side": signal.side,
                "entry": signal.entry_price,
                "sl": signal.stop_loss,
                "tp": signal.take_profit,
                "order_type": signal.order_type,
                "validity_bars": signal.validity_bars,
                "risk_pips": signal.calculate_risk_pips(),
                "rr_ratio": round(signal.calculate_rr_ratio(), 2)
            },
            "raw": data
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400


@app.route("/status", methods=["GET"])
@require_auth
def status():
    """Get system status"""
    config = get_config()
    placer = get_order_placer()
    
    broker_status = {}
    for broker_id, broker in placer.brokers.items():
        broker_status[broker_id] = {
            "name": broker.name,
            "connected": broker.is_connected,
            "type": broker.config.get("type", "unknown")
        }
    
    return jsonify({
        "status": "ok",
        "brokers": broker_status,
        "config": {
            "risk_percent": config.general.risk_percent,
            "order_timeout_candles": config.general.order_timeout_candles,
            "candle_timeframe": config.general.candle_timeframe_minutes
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


@app.route("/queue", methods=["GET"])
@require_auth
def queue_status():
    """Get signal queue status"""
    return jsonify({
        "queue_size": _signal_queue.qsize(),
        "worker_running": _queue_worker_started,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


def run_server(host: str = "0.0.0.0", port: int = 5000, debug: bool = False):
    """Run the webhook server"""
    # Load config first
    load_config()
    config = get_config()
    
    host = host or config.webhook.host
    port = port or config.webhook.port
    
    print(f"🚀 Starting webhook server on {host}:{port}")
    print(f"   Endpoints:")
    print(f"   - POST /webhook        - Receive TradingView alerts")
    print(f"   - POST /webhook/test   - Test alert parsing")
    print(f"   - GET  /health         - Health check")
    print(f"   - GET  /status         - System status")
    print(f"   - GET  /queue          - Queue status")
    
    # Pre-initialize order placer
    get_order_placer()
    
    # Start the signal queue worker
    start_queue_worker()
    print(f"   ✅ Signal queue worker started")
    
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Trading Webhook Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind to")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    
    args = parser.parse_args()
    run_server(args.host, args.port, args.debug)
