#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Health Monitor - Surveillance du système et alertes

Ce script surveille l'état du système et envoie des alertes en cas de problème.
Peut être exécuté via cron ou systemd timer.

Usage:
    python monitor.py check              # Vérification unique
    python monitor.py watch --interval 60  # Surveillance continue
"""

import os
import sys
import time
import json
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import click
from rich.console import Console
from rich.table import Table

console = Console()


def get_version() -> str:
    """Read version from VERSION file"""
    version_file = Path(__file__).parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "unknown"


class HealthMonitor:
    """Moniteur de santé du système"""
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path
        self.checks: List[Dict] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []
        
    def check_webhook_health(self, host: str = "localhost", port: int = 5000) -> Tuple[bool, str]:
        """Vérifier que le webhook répond"""
        try:
            url = f"http://{host}:{port}/health"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                return True, f"Webhook OK - Uptime: {data.get('uptime', 'unknown')}"
            else:
                return False, f"Webhook returned {response.status_code}"
        except requests.exceptions.ConnectionError:
            return False, "Webhook not reachable (connection refused)"
        except Exception as e:
            return False, f"Webhook error: {str(e)}"
    
    def check_broker_connection(self, broker_id: str, broker_config: dict) -> Tuple[bool, str]:
        """Vérifier la connexion à un broker"""
        try:
            from brokers import create_broker
            
            broker = create_broker(broker_id, broker_config, sync=True)
            if broker.connect():
                account_info = broker.get_account_info()
                broker.disconnect()
                if account_info:
                    return True, f"Connected - Balance: ${account_info.balance:,.2f}"
                return True, "Connected (no account info)"
            return False, "Failed to connect"
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    def check_logs(self, log_dir: Path, max_age_hours: int = 1) -> Tuple[bool, str]:
        """Vérifier les erreurs récentes dans les logs"""
        errors_log = log_dir / "errors.log"
        
        if not errors_log.exists():
            return True, "No errors.log file"
        
        # Lire les dernières erreurs
        recent_errors = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        
        try:
            with open(errors_log, "r") as f:
                lines = f.readlines()[-100:]  # Dernières 100 lignes
                
            for line in lines:
                if "[ERROR" in line:
                    # Extraire la date
                    try:
                        date_str = line[1:20]  # Format: 2026-01-22 10:30:45
                        log_time = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                        log_time = log_time.replace(tzinfo=timezone.utc)
                        if log_time > cutoff:
                            recent_errors.append(line.strip()[:100])
                    except:
                        pass
            
            if recent_errors:
                return False, f"{len(recent_errors)} error(s) in last {max_age_hours}h"
            return True, "No recent errors"
            
        except Exception as e:
            return False, f"Error reading logs: {e}"
    
    def check_pending_orders_age(self, max_age_hours: int = 24) -> Tuple[bool, str]:
        """Vérifier qu'il n'y a pas d'ordres très anciens"""
        try:
            from config import load_config
            from brokers import create_broker
            
            cfg = load_config()
            old_orders = []
            cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
            
            for broker_id, broker_cfg in cfg.get_enabled_brokers().items():
                broker = create_broker(broker_id, broker_cfg, sync=True)
                if broker.connect():
                    orders = broker.get_pending_orders()
                    for order in orders:
                        if order.created_time and order.created_time < cutoff:
                            old_orders.append(f"{broker_id}:{order.symbol}")
                    broker.disconnect()
            
            if old_orders:
                return False, f"{len(old_orders)} order(s) older than {max_age_hours}h: {', '.join(old_orders[:3])}"
            return True, "No old pending orders"
            
        except Exception as e:
            return False, f"Error checking orders: {e}"
    
    def check_disk_space(self, min_free_gb: float = 1.0) -> Tuple[bool, str]:
        """Vérifier l'espace disque disponible"""
        try:
            import shutil
            total, used, free = shutil.disk_usage("/")
            free_gb = free / (1024**3)
            
            if free_gb < min_free_gb:
                return False, f"Low disk space: {free_gb:.1f}GB free"
            return True, f"Disk OK: {free_gb:.1f}GB free"
            
        except Exception as e:
            return False, f"Error: {e}"
    
    def check_services_running(self) -> Tuple[bool, str]:
        """Vérifier que les services systemd sont actifs"""
        try:
            import subprocess
            
            services = ["envolees-webhook", "envolees-cleaner"]
            results = []
            
            for service in services:
                result = subprocess.run(
                    ["systemctl", "--user", "is-active", service],
                    capture_output=True, text=True
                )
                status = result.stdout.strip()
                if status != "active":
                    results.append(f"{service}: {status}")
            
            if results:
                return False, f"Services not active: {', '.join(results)}"
            return True, "All services running"
            
        except Exception as e:
            return False, f"Error: {e}"
    
    def run_all_checks(self, webhook_port: int = 5000) -> Dict:
        """Exécuter tous les checks"""
        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": get_version(),
            "checks": {},
            "healthy": True,
            "errors": [],
            "warnings": []
        }
        
        # 1. Webhook
        ok, msg = self.check_webhook_health("localhost", webhook_port)
        results["checks"]["webhook"] = {"ok": ok, "message": msg}
        if not ok:
            results["errors"].append(f"Webhook: {msg}")
        
        # 2. Services
        ok, msg = self.check_services_running()
        results["checks"]["services"] = {"ok": ok, "message": msg}
        if not ok:
            results["errors"].append(f"Services: {msg}")
        
        # 3. Disk space
        ok, msg = self.check_disk_space()
        results["checks"]["disk"] = {"ok": ok, "message": msg}
        if not ok:
            results["warnings"].append(f"Disk: {msg}")
        
        # 4. Recent errors in logs
        log_dir = Path.cwd() / "logs"
        ok, msg = self.check_logs(log_dir)
        results["checks"]["logs"] = {"ok": ok, "message": msg}
        if not ok:
            results["warnings"].append(f"Logs: {msg}")
        
        # 5. Old pending orders
        ok, msg = self.check_pending_orders_age()
        results["checks"]["orders"] = {"ok": ok, "message": msg}
        if not ok:
            results["warnings"].append(f"Orders: {msg}")
        
        # Overall health
        results["healthy"] = len(results["errors"]) == 0
        
        return results
    
    def send_alert(self, results: Dict, channels: List[str]):
        """Envoyer une alerte si problème détecté"""
        if results["healthy"] and not results["warnings"]:
            return  # Tout va bien
        
        # Construire le message
        if not results["healthy"]:
            title = "🚨 ALERT: Trading System Error"
            priority = "high"
        else:
            title = "⚠️ WARNING: Trading System"
            priority = "normal"
        
        message = f"Version: {results['version']}\n"
        message += f"Time: {results['timestamp']}\n\n"
        
        if results["errors"]:
            message += "ERRORS:\n"
            for err in results["errors"]:
                message += f"  • {err}\n"
        
        if results["warnings"]:
            message += "\nWARNINGS:\n"
            for warn in results["warnings"]:
                message += f"  • {warn}\n"
        
        # Envoyer via Apprise si configuré
        try:
            import apprise
            apobj = apprise.Apprise()
            for channel in channels:
                apobj.add(channel)
            apobj.notify(title=title, body=message)
        except ImportError:
            # Apprise non installé, afficher dans la console
            console.print(f"[red]{title}[/red]")
            console.print(message)


@click.group()
def main():
    """Health Monitor - Surveillance du système de trading"""
    pass


@main.command("check")
@click.option("--port", "-p", default=5000, type=int, help="Webhook port")
@click.option("--json-output", is_flag=True, help="Output as JSON")
def check(port, json_output):
    """Run health checks once"""
    monitor = HealthMonitor()
    results = monitor.run_all_checks(webhook_port=port)
    
    if json_output:
        print(json.dumps(results, indent=2))
        return
    
    # Display table
    table = Table(title=f"Health Check - v{results['version']}")
    table.add_column("Check", style="cyan")
    table.add_column("Status")
    table.add_column("Message")
    
    for check_name, check_result in results["checks"].items():
        status = "[green]✅[/green]" if check_result["ok"] else "[red]❌[/red]"
        table.add_row(check_name, status, check_result["message"])
    
    console.print(table)
    
    # Summary
    if results["healthy"]:
        console.print("\n[green]✅ System healthy[/green]")
    else:
        console.print("\n[red]❌ System has errors![/red]")
        for err in results["errors"]:
            console.print(f"  [red]• {err}[/red]")
    
    if results["warnings"]:
        console.print("\n[yellow]⚠️ Warnings:[/yellow]")
        for warn in results["warnings"]:
            console.print(f"  [yellow]• {warn}[/yellow]")
    
    # Exit code
    sys.exit(0 if results["healthy"] else 1)


@main.command("watch")
@click.option("--interval", "-i", default=60, type=int, help="Check interval in seconds")
@click.option("--port", "-p", default=5000, type=int, help="Webhook port")
@click.option("--alert-channel", "-a", multiple=True, help="Alert channel (apprise format)")
def watch(interval, port, alert_channel):
    """Continuous monitoring"""
    monitor = HealthMonitor()
    channels = list(alert_channel)
    
    console.print(f"[cyan]Starting health monitor (interval: {interval}s)[/cyan]")
    if channels:
        console.print(f"[cyan]Alert channels: {len(channels)}[/cyan]")
    
    last_healthy = True
    
    try:
        while True:
            results = monitor.run_all_checks(webhook_port=port)
            
            status = "[green]✅ Healthy[/green]" if results["healthy"] else "[red]❌ Unhealthy[/red]"
            console.print(f"[{datetime.now().strftime('%H:%M:%S')}] {status}")
            
            # Alert on state change or persistent errors
            if not results["healthy"] or (results["warnings"] and not last_healthy):
                if channels:
                    monitor.send_alert(results, channels)
                else:
                    for err in results["errors"]:
                        console.print(f"  [red]• {err}[/red]")
            
            last_healthy = results["healthy"]
            time.sleep(interval)
            
    except KeyboardInterrupt:
        console.print("\n[yellow]Monitor stopped[/yellow]")


if __name__ == "__main__":
    main()
