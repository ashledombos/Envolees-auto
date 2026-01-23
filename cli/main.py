#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trading Automation CLI
Main command-line interface for testing and management
"""

import os
import sys
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

from config import load_config, get_config, save_config

console = Console()


def get_version() -> str:
    """Read version from VERSION file"""
    version_file = Path(__file__).parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "unknown"


@click.group()
@click.option("--config", "-c", "config_path", help="Path to config file")
@click.version_option(version=get_version(), prog_name="envolees-auto")
@click.pass_context
def cli(ctx, config_path):
    """Trading Automation CLI - Manage brokers, orders, and signals"""
    ctx.ensure_object(dict)
    
    if config_path:
        os.environ["TRADING_CONFIG_PATH"] = config_path
    
    load_config()


# ============ VERSION COMMAND ============

@cli.command("version")
def version_cmd():
    """Show version and system info"""
    version = get_version()
    
    console.print(Panel(f"[bold cyan]Envolées Auto v{version}[/bold cyan]"))
    
    # Check config files
    from pathlib import Path
    config_dir = Path.cwd() / "config"
    
    table = Table(title="Configuration Files")
    table.add_column("File", style="cyan")
    table.add_column("Status", style="green")
    
    files = {
        "settings.yaml": "Main config",
        "secrets.yaml": "Credentials (optional)",
        "instruments.yaml": "Instruments (optional)"
    }
    
    for filename, desc in files.items():
        path = config_dir / filename
        if path.exists():
            table.add_row(f"{filename}", f"✅ Found - {desc}")
        else:
            example = config_dir / f"{filename.replace('.yaml', '.example.yaml')}"
            if example.exists():
                table.add_row(f"{filename}", f"⚠️  Missing (example available)")
            else:
                table.add_row(f"{filename}", f"❌ Not found")
    
    console.print(table)


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


# ============ ORDERS CHECK COMMAND ============

@order.command("check")
@click.option("--broker", "-b", help="Specific broker (default: all)")
def order_check(broker):
    """Check pending orders with risk analysis"""
    from brokers import create_broker
    from services.position_sizer import PositionSizer
    
    cfg = get_config()
    brokers_to_check = [broker] if broker else list(cfg.get_enabled_brokers().keys())
    
    console.print(Panel("[bold]Pending Orders Risk Analysis[/bold]"))
    
    for broker_id in brokers_to_check:
        if broker_id not in cfg.brokers:
            console.print(f"[red]Broker '{broker_id}' not found[/red]")
            continue
        
        broker_cfg = cfg.brokers[broker_id]
        broker_obj = create_broker(broker_id, broker_cfg, sync=True)
        
        try:
            if not broker_obj.connect():
                console.print(f"[red]Failed to connect to {broker_id}[/red]")
                continue
            
            # Get account info
            account_info = broker_obj.get_account_info()
            balance = account_info.balance if account_info else 0
            equity = account_info.equity if account_info else balance
            
            console.print(f"\n[bold cyan]--- {broker_cfg.get('name', broker_id)} ---[/bold cyan]")
            console.print(f"Balance: ${balance:,.2f} | Equity: ${equity:,.2f}")
            
            # Get pending orders
            orders = broker_obj.get_pending_orders()
            
            if not orders:
                console.print("[dim]No pending orders[/dim]")
                continue
            
            # Create table
            table = Table(title=f"Pending Orders ({len(orders)})")
            table.add_column("ID", style="cyan", max_width=15)
            table.add_column("Symbol", style="yellow")
            table.add_column("Side")
            table.add_column("Lots", justify="right")
            table.add_column("Entry", justify="right")
            table.add_column("SL", justify="right")
            table.add_column("TP", justify="right")
            table.add_column("SL Pips", justify="right")
            table.add_column("Risk $", justify="right")
            table.add_column("Risk %", justify="right")
            table.add_column("Created")
            
            total_risk = 0
            
            for order in orders:
                # Get instrument config
                inst_cfg = cfg.get_instrument_config(order.symbol) or {}
                pip_size = inst_cfg.get("pip_size", 0.0001)
                pip_value = inst_cfg.get("pip_value_per_lot")
                quote_currency = inst_cfg.get("quote_currency")
                
                # Calculate SL pips
                sl_pips = 0
                risk_amount = 0
                risk_percent = 0
                
                if order.stop_loss and order.entry_price:
                    sl_distance = abs(order.entry_price - order.stop_loss)
                    sl_pips = sl_distance / pip_size
                    
                    # Calculate pip value
                    if pip_value is None and quote_currency:
                        # Dynamic calculation
                        base_pip_value = 100000 * pip_size
                        pip_value = base_pip_value / order.entry_price
                    elif pip_value is None:
                        pip_value = 10  # Default
                    
                    # Calculate risk
                    risk_amount = order.volume * sl_pips * pip_value
                    risk_percent = (risk_amount / equity * 100) if equity > 0 else 0
                    total_risk += risk_amount
                
                # Format side with color
                side_str = f"[green]{order.side.value}[/green]" if order.side.value == "BUY" else f"[red]{order.side.value}[/red]"
                
                # Risk color
                if risk_percent > 1.0:
                    risk_color = "red"
                elif risk_percent > 0.6:
                    risk_color = "yellow"
                else:
                    risk_color = "green"
                
                table.add_row(
                    order.order_id[:15] if len(order.order_id) > 15 else order.order_id,
                    order.symbol,
                    side_str,
                    f"{order.volume:.2f}",
                    f"{order.entry_price:.5f}",
                    f"{order.stop_loss:.5f}" if order.stop_loss else "-",
                    f"{order.take_profit:.5f}" if order.take_profit else "-",
                    f"{sl_pips:.1f}",
                    f"${risk_amount:.2f}",
                    f"[{risk_color}]{risk_percent:.2f}%[/{risk_color}]",
                    order.created_time.strftime("%d/%m %H:%M") if order.created_time else "-"
                )
            
            console.print(table)
            
            # Summary
            total_risk_percent = (total_risk / equity * 100) if equity > 0 else 0
            console.print(f"[bold]Total pending risk: ${total_risk:,.2f} ({total_risk_percent:.2f}%)[/bold]")
        
        finally:
            broker_obj.disconnect()


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


# ============ SIGNAL SIMULATION COMMANDS ============

@cli.group()
def signal():
    """Signal testing and simulation"""
    pass


@signal.command("simulate")
@click.option("--symbol", "-s", required=True, help="Trading symbol (e.g., EURUSD)")
@click.option("--side", type=click.Choice(["buy", "sell", "long", "short"]), required=True, help="Trade direction")
@click.option("--entry", "-e", type=float, required=True, help="Entry price")
@click.option("--sl", type=float, required=True, help="Stop loss price")
@click.option("--tp", type=float, help="Take profit price (optional)")
@click.option("--broker", "-b", multiple=True, help="Specific broker(s) to test (can be used multiple times)")
@click.option("--dry-run", is_flag=True, default=True, help="Simulate without placing real orders (default)")
@click.option("--live", is_flag=True, help="Actually place the orders (CAUTION!)")
def signal_simulate(symbol, side, entry, sl, tp, broker, dry_run, live):
    """
    Simulate a TradingView signal on all or specific brokers.
    
    Examples:
    
      # Dry run on all brokers
      signal simulate -s EURUSD --side buy -e 1.0850 --sl 1.0800 --tp 1.0950
      
      # Dry run on specific broker
      signal simulate -s XAUUSD --side sell -e 2650 --sl 2670 --tp 2610 -b ftmo_ctrader
      
      # LIVE order (be careful!)
      signal simulate -s EURUSD --side buy -e 1.0850 --sl 1.0800 --live
    """
    from services.order_placer import OrderPlacerSync, SignalData
    
    # Calculate TP if not provided (use default RR)
    cfg = get_config()
    if tp is None:
        risk = abs(entry - sl)
        rr = cfg.general.default_rr_ratio
        if side.lower() in ["buy", "long"]:
            tp = entry + (risk * rr)
        else:
            tp = entry - (risk * rr)
    
    # Create signal
    signal_data = SignalData(
        symbol=symbol.upper(),
        side=side.upper(),
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        order_type="LIMIT",
        validity_bars=cfg.general.order_timeout_candles,
        timeframe=f"M{cfg.general.candle_timeframe_minutes}"
    )
    
    is_dry_run = not live
    
    # Show signal info
    console.print(Panel(f"[bold]{'🧪 DRY RUN' if is_dry_run else '🔴 LIVE ORDER'} - Signal Simulation[/bold]"))
    
    table = Table(title="Signal Details")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Symbol", signal_data.symbol)
    table.add_row("Side", signal_data.side)
    table.add_row("Entry", f"{signal_data.entry_price}")
    table.add_row("Stop Loss", f"{signal_data.stop_loss}")
    table.add_row("Take Profit", f"{signal_data.take_profit}")
    table.add_row("Risk (pips)", f"{signal_data.calculate_risk_pips():.1f}")
    
    console.print(table)
    
    if live:
        if not click.confirm("⚠️  This will place REAL orders. Continue?"):
            console.print("[yellow]Cancelled.[/yellow]")
            return
    
    # Execute
    placer = OrderPlacerSync()
    
    try:
        console.print("\n[bold]Connecting to brokers...[/bold]")
        if not placer.connect():
            console.print("[red]Failed to connect to all brokers[/red]")
            return
        
        target_brokers = list(broker) if broker else None
        
        console.print(f"\n[bold]{'Simulating' if is_dry_run else 'Placing'} orders...[/bold]\n")
        results = placer.place_signal(signal_data, brokers=target_brokers, dry_run=is_dry_run)
        
        # Results table
        table = Table(title="Results")
        table.add_column("Broker", style="cyan")
        table.add_column("Status")
        table.add_column("Lots")
        table.add_column("Risk $")
        table.add_column("Message")
        
        for broker_id, result in results.items():
            if result.success:
                status = "[green]✅ Success[/green]"
                lots = f"{result.position_size.lots:.2f}" if result.position_size else "-"
                risk = f"${result.position_size.risk_amount:.2f}" if result.position_size else "-"
                msg = result.order_result.message if result.order_result else ""
            else:
                status = "[red]❌ Failed[/red]"
                lots = "-"
                risk = "-"
                if result.filter_result:
                    msg = f"[yellow]Filter: {result.filter_result.message}[/yellow]"
                else:
                    msg = result.error or "Unknown error"
            
            table.add_row(result.broker_name, status, lots, risk, msg)
        
        console.print(table)
        
    finally:
        placer.disconnect()


@signal.command("check-filters")
@click.option("--symbol", "-s", required=True, help="Trading symbol")
@click.option("--side", type=click.Choice(["buy", "sell"]), default="buy", help="Trade direction")
@click.option("--entry", "-e", type=float, default=1.0, help="Entry price")
@click.option("--sl", type=float, default=0.99, help="Stop loss price")
def signal_check_filters(symbol, side, entry, sl):
    """
    Check which brokers would accept a signal (without placing orders).
    
    Example:
      signal check-filters -s EURUSD
    """
    from services.order_placer import OrderPlacerSync, SignalData
    
    signal_data = SignalData(
        symbol=symbol.upper(),
        side=side.upper(),
        entry_price=entry,
        stop_loss=sl,
        take_profit=entry + abs(entry - sl) * 2
    )
    
    console.print(Panel(f"[bold]Filter Check for {symbol}[/bold]"))
    
    placer = OrderPlacerSync()
    
    try:
        if not placer.connect():
            console.print("[red]Failed to connect[/red]")
            return
        
        table = Table(title="Filter Results")
        table.add_column("Broker", style="cyan")
        table.add_column("Symbol Mapped")
        table.add_column("Filter Status")
        table.add_column("Details")
        
        cfg = get_config()
        
        for broker_id in placer.placer.brokers.keys():
            broker = placer.placer.brokers[broker_id]
            
            # Check instrument mapping
            broker_symbol = cfg.get_instrument_symbol(symbol.upper(), broker_id)
            
            # Check filters
            result = placer.check_filters(broker_id, signal_data)
            
            if result.passed:
                status = "[green]✅ PASS[/green]"
            else:
                status = f"[red]❌ {result.filter_result.value}[/red]"
            
            table.add_row(
                broker.name,
                broker_symbol or "[red]Not mapped[/red]",
                status,
                result.message
            )
        
        console.print(table)
        
    finally:
        placer.disconnect()


@signal.command("list-instruments")
def signal_list_instruments():
    """Show all configured instruments and their broker mappings"""
    cfg = get_config()
    
    if not cfg.instruments:
        console.print("[yellow]No instruments configured in settings.yaml[/yellow]")
        return
    
    # Get all broker IDs
    broker_ids = list(cfg.brokers.keys())
    
    table = Table(title="Instrument Mappings")
    table.add_column("TradingView", style="cyan")
    
    for broker_id in broker_ids:
        broker_name = cfg.brokers[broker_id].get("name", broker_id)
        table.add_column(broker_name)
    
    table.add_column("Pip Size")
    table.add_column("Pip Value")
    
    for tv_symbol, instrument in cfg.instruments.items():
        row = [tv_symbol]
        
        for broker_id in broker_ids:
            broker_symbol = instrument.get(broker_id)
            if broker_symbol:
                row.append(f"[green]{broker_symbol}[/green]")
            else:
                row.append("[dim]-[/dim]")
        
        row.append(str(instrument.get("pip_size", "-")))
        pip_val = instrument.get("pip_value_per_lot")
        row.append(str(pip_val) if pip_val else "[dim]dynamic[/dim]")
        
        table.add_row(*row)
    
    console.print(table)


# ============ CLEANER COMMAND ============

@cli.group("cleaner")
def cleaner():
    """Order cleaner commands (cancel expired pending orders)"""
    pass


@cleaner.command("start")
@click.option("--interval", "-i", default=900, type=int, help="Check interval in seconds (default: 900 = 15min)")
def cleaner_start(interval):
    """Start the order cleaner daemon"""
    import time
    from services.order_cleaner import OrderCleanerSync
    
    cfg = get_config()
    timeout_candles = cfg.general.order_timeout_candles
    
    cleaner_service = OrderCleanerSync(cfg)
    
    interval_display = f"{interval//60}min" if interval >= 60 else f"{interval}s"
    console.print(f"[green]🧹 Order cleaner started[/green]")
    console.print(f"   Interval: {interval_display} | Timeout: {timeout_candles} candles (4H)")
    
    try:
        if not cleaner_service.connect():
            console.print("[red]Failed to connect to brokers[/red]")
            return
        
        console.print("[green]✅ Connected to brokers[/green]")
        
        # Main loop
        while True:
            try:
                results = cleaner_service.cleanup_all()
                total_cancelled = sum(r.get("orders_cancelled", 0) for r in results.values())
                if total_cancelled > 0:
                    console.print(f"[yellow]🗑️ Cancelled {total_cancelled} expired orders[/yellow]")
            except Exception as e:
                console.print(f"[red]Error in cleaner: {e}[/red]")
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        console.print("\n[yellow]Cleaner stopped[/yellow]")
    finally:
        cleaner_service.disconnect()


@cleaner.command("run-once")
def cleaner_run_once():
    """Run cleaner once and exit"""
    from services.order_cleaner import OrderCleanerSync
    
    cfg = get_config()
    cleaner_service = OrderCleanerSync(cfg)
    
    try:
        if not cleaner_service.connect():
            console.print("[red]Failed to connect to brokers[/red]")
            return
        
        results = cleaner_service.cleanup_all()
        
        total_cancelled = sum(r.get("orders_cancelled", 0) for r in results.values())
        if total_cancelled == 0:
            console.print("[dim]No expired orders found[/dim]")
    finally:
        cleaner_service.disconnect()


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
