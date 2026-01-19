#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trading Automation CLI
Main command-line interface for testing and management
"""

import os
import sys
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

from config import load_config, get_config, save_config

console = Console()


@click.group()
@click.option("--config", "-c", "config_path", help="Path to config file")
@click.pass_context
def cli(ctx, config_path):
    """Trading Automation CLI - Manage brokers, orders, and signals"""
    ctx.ensure_object(dict)
    
    if config_path:
        os.environ["TRADING_CONFIG_PATH"] = config_path
    
    load_config()


# ============ CONFIG COMMANDS ============

@cli.group()
def config():
    """Configuration management"""
    pass


@config.command("show")
def config_show():
    """Show current configuration"""
    cfg = get_config()
    
    console.print(Panel("[bold]Current Configuration[/bold]"))
    
    # General
    table = Table(title="General Settings")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Risk %", f"{cfg.general.risk_percent}%")
    table.add_row("Default R:R", str(cfg.general.default_rr_ratio))
    table.add_row("Order Timeout", f"{cfg.general.order_timeout_candles} candles")
    table.add_row("Timeframe", f"{cfg.general.candle_timeframe_minutes} min")
    
    console.print(table)
    
    # Brokers
    table = Table(title="Brokers")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Enabled", style="green")
    
    for broker_id, broker_cfg in cfg.brokers.items():
        table.add_row(
            broker_id,
            broker_cfg.get("name", ""),
            broker_cfg.get("type", ""),
            "✅" if broker_cfg.get("enabled") else "❌"
        )
    
    console.print(table)


@config.command("validate")
def config_validate():
    """Validate configuration"""
    try:
        cfg = get_config()
        
        errors = []
        warnings = []
        
        # Check webhook
        if cfg.webhook.secret_token == "CHANGE_ME":
            warnings.append("Webhook secret token not set")
        
        # Check brokers
        for broker_id, broker_cfg in cfg.brokers.items():
            if not broker_cfg.get("enabled"):
                continue
            
            btype = broker_cfg.get("type")
            
            if btype == "ctrader":
                if not broker_cfg.get("client_id"):
                    errors.append(f"{broker_id}: Missing client_id")
                if not broker_cfg.get("client_secret"):
                    errors.append(f"{broker_id}: Missing client_secret")
                if not broker_cfg.get("access_token"):
                    errors.append(f"{broker_id}: Missing access_token")
                if not broker_cfg.get("account_id"):
                    errors.append(f"{broker_id}: Missing account_id")
            
            elif btype == "tradelocker":
                if not broker_cfg.get("email"):
                    errors.append(f"{broker_id}: Missing email")
                if not broker_cfg.get("password"):
                    errors.append(f"{broker_id}: Missing password")
        
        if errors:
            console.print("[red bold]Errors:[/red bold]")
            for err in errors:
                console.print(f"  ❌ {err}")
        
        if warnings:
            console.print("[yellow bold]Warnings:[/yellow bold]")
            for warn in warnings:
                console.print(f"  ⚠️  {warn}")
        
        if not errors and not warnings:
            console.print("[green]✅ Configuration is valid[/green]")
        
    except Exception as e:
        console.print(f"[red]❌ Configuration error: {e}[/red]")


# ============ BROKER COMMANDS ============

@cli.group()
def broker():
    """Broker management and testing"""
    pass


@broker.command("list")
def broker_list():
    """List configured brokers"""
    cfg = get_config()
    
    table = Table(title="Configured Brokers")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Enabled")
    table.add_column("Demo")
    
    for broker_id, broker_cfg in cfg.brokers.items():
        table.add_row(
            broker_id,
            broker_cfg.get("name", ""),
            broker_cfg.get("type", ""),
            "✅" if broker_cfg.get("enabled") else "❌",
            "Yes" if broker_cfg.get("is_demo", True) else "No"
        )
    
    console.print(table)


@broker.command("test")
@click.argument("broker_id")
def broker_test(broker_id):
    """Test connection to a broker"""
    cfg = get_config()
    
    if broker_id not in cfg.brokers:
        console.print(f"[red]Broker '{broker_id}' not found[/red]")
        return
    
    broker_cfg = cfg.brokers[broker_id]
    console.print(f"[cyan]Testing connection to {broker_cfg.get('name', broker_id)}...[/cyan]")
    
    from brokers import create_broker
    
    broker = create_broker(broker_id, broker_cfg, sync=True)
    if not broker:
        console.print("[red]Failed to create broker instance[/red]")
        return
    
    try:
        if broker.connect():
            console.print("[green]✅ Connected successfully[/green]")
            
            # Get account info
            account = broker.get_account_info()
            if account:
                table = Table(title="Account Info")
                table.add_column("Field", style="cyan")
                table.add_column("Value", style="green")
                
                table.add_row("Account ID", str(account.account_id))
                table.add_row("Balance", f"{account.balance:.2f} {account.currency}")
                table.add_row("Equity", f"{account.equity:.2f} {account.currency}")
                table.add_row("Margin Free", f"{account.margin_free:.2f}")
                table.add_row("Leverage", f"1:{account.leverage}")
                table.add_row("Demo", "Yes" if account.is_demo else "No")
                
                console.print(table)
            
            # Get symbols count
            symbols = broker.get_symbols()
            console.print(f"[cyan]Available symbols: {len(symbols)}[/cyan]")
            
        else:
            console.print("[red]❌ Connection failed[/red]")
    
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
    finally:
        broker.disconnect()


@broker.command("symbols")
@click.argument("broker_id")
@click.option("--search", "-s", help="Search filter")
@click.option("--limit", "-n", default=50, help="Max symbols to show")
def broker_symbols(broker_id, search, limit):
    """List available symbols for a broker"""
    cfg = get_config()
    
    if broker_id not in cfg.brokers:
        console.print(f"[red]Broker '{broker_id}' not found[/red]")
        return
    
    from brokers import create_broker
    
    broker = create_broker(broker_id, cfg.brokers[broker_id], sync=True)
    
    try:
        if not broker.connect():
            console.print("[red]Failed to connect[/red]")
            return
        
        symbols = broker.get_symbols()
        
        if search:
            search = search.upper()
            symbols = [s for s in symbols if search in s.symbol.upper()]
        
        table = Table(title=f"Symbols ({len(symbols)} total)")
        table.add_column("Symbol", style="cyan")
        table.add_column("Broker ID")
        table.add_column("Description")
        
        for s in symbols[:limit]:
            table.add_row(s.symbol, s.broker_symbol, s.description[:50] if s.description else "")
        
        console.print(table)
        
        if len(symbols) > limit:
            console.print(f"[yellow]... and {len(symbols) - limit} more[/yellow]")
    
    finally:
        broker.disconnect()


@broker.command("orders")
@click.argument("broker_id")
def broker_orders(broker_id):
    """List pending orders for a broker"""
    cfg = get_config()
    
    if broker_id not in cfg.brokers:
        console.print(f"[red]Broker '{broker_id}' not found[/red]")
        return
    
    from brokers import create_broker
    
    broker = create_broker(broker_id, cfg.brokers[broker_id], sync=True)
    
    try:
        if not broker.connect():
            console.print("[red]Failed to connect[/red]")
            return
        
        orders = broker.get_pending_orders()
        
        if not orders:
            console.print("[yellow]No pending orders[/yellow]")
            return
        
        table = Table(title=f"Pending Orders ({len(orders)})")
        table.add_column("ID", style="cyan")
        table.add_column("Symbol")
        table.add_column("Side")
        table.add_column("Type")
        table.add_column("Volume")
        table.add_column("Entry")
        table.add_column("Created")
        
        for o in orders:
            created = o.created_time.strftime("%m/%d %H:%M") if o.created_time else "N/A"
            table.add_row(
                o.order_id[:16] + "...",
                o.symbol,
                o.side.value,
                o.order_type.value,
                f"{o.volume:.2f}",
                f"{o.entry_price:.5f}",
                created
            )
        
        console.print(table)
    
    finally:
        broker.disconnect()


@broker.command("positions")
@click.argument("broker_id")
def broker_positions(broker_id):
    """List open positions for a broker"""
    cfg = get_config()
    
    if broker_id not in cfg.brokers:
        console.print(f"[red]Broker '{broker_id}' not found[/red]")
        return
    
    from brokers import create_broker
    
    broker = create_broker(broker_id, cfg.brokers[broker_id], sync=True)
    
    try:
        if not broker.connect():
            console.print("[red]Failed to connect[/red]")
            return
        
        positions = broker.get_positions()
        
        if not positions:
            console.print("[yellow]No open positions[/yellow]")
            return
        
        table = Table(title=f"Open Positions ({len(positions)})")
        table.add_column("ID", style="cyan")
        table.add_column("Symbol")
        table.add_column("Side")
        table.add_column("Volume")
        table.add_column("Entry")
        table.add_column("P/L")
        
        for p in positions:
            pl_color = "green" if (p.profit or 0) >= 0 else "red"
            table.add_row(
                p.position_id[:16] + "...",
                p.symbol,
                p.side.value,
                f"{p.volume:.2f}",
                f"{p.entry_price:.5f}",
                f"[{pl_color}]{p.profit or 0:.2f}[/{pl_color}]"
            )
        
        console.print(table)
    
    finally:
        broker.disconnect()


# ============ ORDER COMMANDS ============

@cli.group()
def order():
    """Order management"""
    pass


@order.command("place")
@click.argument("broker_id")
@click.argument("symbol")
@click.argument("side", type=click.Choice(["BUY", "SELL", "LONG", "SHORT"]))
@click.option("--entry", "-e", type=float, required=True, help="Entry price")
@click.option("--sl", type=float, required=True, help="Stop loss price")
@click.option("--tp", type=float, required=True, help="Take profit price")
@click.option("--volume", "-v", type=float, help="Volume in lots (calculated if not provided)")
@click.option("--type", "order_type", default="LIMIT", type=click.Choice(["LIMIT", "STOP", "MARKET"]))
@click.option("--validity", default=1, type=int, help="Validity in bars")
@click.option("--dry-run", is_flag=True, help="Don't actually place the order")
def order_place(broker_id, symbol, side, entry, sl, tp, volume, order_type, validity, dry_run):
    """Place an order manually"""
    cfg = get_config()
    
    if broker_id not in cfg.brokers:
        console.print(f"[red]Broker '{broker_id}' not found[/red]")
        return
    
    from services.order_placer import OrderPlacerSync, SignalData
    
    # Create signal
    signal = SignalData(
        symbol=symbol,
        side="LONG" if side in ["BUY", "LONG"] else "SHORT",
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        order_type=order_type,
        validity_bars=validity
    )
    
    console.print(Panel(f"[bold]{side} {symbol}[/bold]"))
    console.print(f"  Entry: {entry}")
    console.print(f"  SL: {sl}")
    console.print(f"  TP: {tp}")
    console.print(f"  R:R: {signal.calculate_rr_ratio():.2f}")
    console.print(f"  Risk: {signal.calculate_risk_pips():.5f}")
    
    if dry_run:
        console.print("[yellow]Dry run - order not placed[/yellow]")
        return
    
    placer = OrderPlacerSync(cfg)
    
    try:
        if not placer.connect():
            console.print("[red]Failed to connect[/red]")
            return
        
        results = placer.place_signal(signal, [broker_id])
        
        for broker, result in results.items():
            if result.success:
                console.print(f"[green]✅ Order placed: {result.order_id}[/green]")
            else:
                console.print(f"[red]❌ Failed: {result.message}[/red]")
    
    finally:
        placer.disconnect()


@order.command("cancel")
@click.argument("broker_id")
@click.argument("order_id")
def order_cancel(broker_id, order_id):
    """Cancel a pending order"""
    cfg = get_config()
    
    if broker_id not in cfg.brokers:
        console.print(f"[red]Broker '{broker_id}' not found[/red]")
        return
    
    from brokers import create_broker
    
    broker = create_broker(broker_id, cfg.brokers[broker_id], sync=True)
    
    try:
        if not broker.connect():
            console.print("[red]Failed to connect[/red]")
            return
        
        result = broker.cancel_order(order_id)
        
        if result.success:
            console.print(f"[green]✅ Order cancelled[/green]")
        else:
            console.print(f"[red]❌ Failed: {result.message}[/red]")
    
    finally:
        broker.disconnect()


# ============ CLEANUP COMMANDS ============

@cli.command("cleanup")
@click.option("--broker", "-b", help="Specific broker (default: all)")
@click.option("--dry-run", is_flag=True, help="Don't cancel, just show expired orders")
def cleanup(broker, dry_run):
    """Clean up expired pending orders"""
    from services.order_cleaner import OrderCleanerSync
    
    cfg = get_config()
    cleaner = OrderCleanerSync(cfg)
    
    try:
        if not cleaner.connect():
            console.print("[red]Failed to connect to brokers[/red]")
            return
        
        if broker:
            results = {broker: cleaner.cleanup_broker(broker)}
        else:
            results = cleaner.cleanup_all()
        
        # Summary table
        table = Table(title="Cleanup Results")
        table.add_column("Broker", style="cyan")
        table.add_column("Checked")
        table.add_column("Expired")
        table.add_column("Cancelled")
        table.add_column("Errors")
        
        for broker_id, stats in results.items():
            table.add_row(
                stats.get("broker", broker_id),
                str(stats.get("orders_checked", 0)),
                str(stats.get("orders_expired", 0)),
                str(stats.get("orders_cancelled", 0)),
                str(len(stats.get("errors", [])))
            )
        
        console.print(table)
    
    finally:
        cleaner.disconnect()


# ============ SERVER COMMAND ============

@cli.command("serve")
@click.option("--host", "-h", default="0.0.0.0", help="Host to bind")
@click.option("--port", "-p", default=5000, type=int, help="Port to bind")
@click.option("--debug", is_flag=True, help="Enable debug mode")
def serve(host, port, debug):
    """Start the webhook server"""
    from webhook.server import run_server
    run_server(host, port, debug)


if __name__ == "__main__":
    cli()
