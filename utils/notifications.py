#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notification service for trading alerts
Supports multiple channels: email, telegram, discord, etc.
"""

import subprocess
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum


class NotificationType(Enum):
    ORDER_PLACED = "order_placed"
    ORDER_FILLED = "order_filled"
    ORDER_EXPIRED = "order_expired"
    ORDER_CANCELLED = "order_cancelled"
    ERROR = "error"
    INFO = "info"


@dataclass
class Notification:
    """Notification data"""
    type: NotificationType
    title: str
    message: str
    broker: str = ""
    symbol: str = ""
    data: Optional[Dict] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    def format_text(self) -> str:
        """Format as plain text"""
        lines = [
            f"📊 {self.title}",
            f"⏰ {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        if self.broker:
            lines.append(f"🏦 Broker: {self.broker}")
        if self.symbol:
            lines.append(f"📈 Symbol: {self.symbol}")
        lines.append("")
        lines.append(self.message)
        
        if self.data:
            lines.append("")
            for key, value in self.data.items():
                lines.append(f"  • {key}: {value}")
        
        return "\n".join(lines)
    
    def format_html(self) -> str:
        """Format as HTML"""
        html = f"""
<h3>{self._get_emoji()} {self.title}</h3>
<p><small>🕐 {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</small></p>
"""
        if self.broker:
            html += f"<p>🏦 <strong>Broker:</strong> {self.broker}</p>"
        if self.symbol:
            html += f"<p>📈 <strong>Symbol:</strong> {self.symbol}</p>"
        
        html += f"<p>{self.message}</p>"
        
        if self.data:
            html += "<ul>"
            for key, value in self.data.items():
                html += f"<li><strong>{key}:</strong> {value}</li>"
            html += "</ul>"
        
        return html
    
    def _get_emoji(self) -> str:
        """Get emoji based on notification type"""
        emojis = {
            NotificationType.ORDER_PLACED: "✅",
            NotificationType.ORDER_FILLED: "🎯",
            NotificationType.ORDER_EXPIRED: "⏰",
            NotificationType.ORDER_CANCELLED: "❌",
            NotificationType.ERROR: "🚨",
            NotificationType.INFO: "ℹ️",
        }
        return emojis.get(self.type, "📢")


class NotificationChannel:
    """Base class for notification channels"""
    
    def __init__(self, config: dict):
        self.config = config
        self.enabled = config.get("enabled", False)
    
    def send(self, notification: Notification) -> bool:
        """Send notification. Override in subclasses."""
        raise NotImplementedError


class EmailChannel(NotificationChannel):
    """Email notification channel using system mail command"""
    
    def send(self, notification: Notification) -> bool:
        if not self.enabled:
            return False
        
        to_email = self.config.get("config", {}).get("to", "")
        if not to_email:
            print("[Notifications] Email: no recipient configured")
            return False
        
        subject = f"[Trading] {notification.title}"
        body = notification.format_text()
        
        try:
            process = subprocess.Popen(
                ['mail', '-s', subject, to_email],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            process.communicate(input=body.encode('utf-8'), timeout=10)
            
            if process.returncode == 0:
                print(f"[Notifications] 📧 Email sent to {to_email}")
                return True
            else:
                print(f"[Notifications] Email failed (code {process.returncode})")
                return False
                
        except FileNotFoundError:
            print("[Notifications] 'mail' command not available")
            return False
        except Exception as e:
            print(f"[Notifications] Email error: {e}")
            return False


class TelegramChannel(NotificationChannel):
    """Telegram notification channel"""
    
    def send(self, notification: Notification) -> bool:
        if not self.enabled:
            return False
        
        import requests
        
        bot_token = self.config.get("config", {}).get("bot_token", "")
        chat_id = self.config.get("config", {}).get("chat_id", "")
        
        if not bot_token or not chat_id:
            print("[Notifications] Telegram: missing bot_token or chat_id")
            return False
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": notification.format_text(),
            "parse_mode": "HTML"
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                print(f"[Notifications] 📱 Telegram sent to {chat_id}")
                return True
            else:
                print(f"[Notifications] Telegram failed: {response.text}")
                return False
        except Exception as e:
            print(f"[Notifications] Telegram error: {e}")
            return False


class DiscordChannel(NotificationChannel):
    """Discord webhook notification channel"""
    
    def send(self, notification: Notification) -> bool:
        if not self.enabled:
            return False
        
        import requests
        
        webhook_url = self.config.get("config", {}).get("webhook_url", "")
        
        if not webhook_url:
            print("[Notifications] Discord: missing webhook_url")
            return False
        
        # Discord embed
        color = {
            NotificationType.ORDER_PLACED: 0x00FF00,  # Green
            NotificationType.ORDER_FILLED: 0x0000FF,  # Blue
            NotificationType.ORDER_EXPIRED: 0xFFA500,  # Orange
            NotificationType.ORDER_CANCELLED: 0xFF0000,  # Red
            NotificationType.ERROR: 0xFF0000,  # Red
            NotificationType.INFO: 0x808080,  # Gray
        }.get(notification.type, 0x808080)
        
        embed = {
            "title": f"{notification._get_emoji()} {notification.title}",
            "description": notification.message,
            "color": color,
            "timestamp": notification.timestamp.isoformat(),
            "fields": []
        }
        
        if notification.broker:
            embed["fields"].append({"name": "Broker", "value": notification.broker, "inline": True})
        if notification.symbol:
            embed["fields"].append({"name": "Symbol", "value": notification.symbol, "inline": True})
        
        if notification.data:
            for key, value in notification.data.items():
                embed["fields"].append({"name": key, "value": str(value), "inline": True})
        
        payload = {"embeds": [embed]}
        
        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
            if response.status_code in [200, 204]:
                print("[Notifications] 💬 Discord sent")
                return True
            else:
                print(f"[Notifications] Discord failed: {response.text}")
                return False
        except Exception as e:
            print(f"[Notifications] Discord error: {e}")
            return False


class NotificationService:
    """Main notification service managing multiple channels"""
    
    def __init__(self, config: dict):
        self.config = config
        self.enabled = config.get("enabled", True)
        self.channels: List[NotificationChannel] = []
        
        # Initialize channels
        for channel_config in config.get("channels", []):
            channel_type = channel_config.get("type", "")
            
            if channel_type == "email":
                self.channels.append(EmailChannel(channel_config))
            elif channel_type == "telegram":
                self.channels.append(TelegramChannel(channel_config))
            elif channel_type == "discord":
                self.channels.append(DiscordChannel(channel_config))
    
    def should_notify(self, notification_type: NotificationType) -> bool:
        """Check if notifications should be sent for this type"""
        if not self.enabled:
            return False
        
        type_mapping = {
            NotificationType.ORDER_PLACED: "on_order_placed",
            NotificationType.ORDER_FILLED: "on_order_placed",
            NotificationType.ORDER_EXPIRED: "on_order_expired",
            NotificationType.ORDER_CANCELLED: "on_order_expired",
            NotificationType.ERROR: "on_error",
            NotificationType.INFO: "on_error",
        }
        
        config_key = type_mapping.get(notification_type)
        return self.config.get(config_key, True)
    
    def notify(self, notification: Notification) -> int:
        """
        Send notification to all enabled channels.
        
        Returns:
            Number of channels that successfully sent the notification
        """
        if not self.should_notify(notification.type):
            return 0
        
        success_count = 0
        for channel in self.channels:
            if channel.enabled:
                try:
                    if channel.send(notification):
                        success_count += 1
                except Exception as e:
                    print(f"[Notifications] Channel error: {e}")
        
        return success_count
    
    def notify_order_placed(
        self, 
        broker: str, 
        symbol: str, 
        side: str, 
        order_type: str,
        volume: float,
        entry_price: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        order_id: str = ""
    ) -> int:
        """Convenience method for order placed notifications"""
        data = {
            "Side": side,
            "Type": order_type,
            "Volume": f"{volume} lots",
            "Entry": f"{entry_price}",
        }
        if stop_loss:
            data["Stop Loss"] = f"{stop_loss}"
        if take_profit:
            data["Take Profit"] = f"{take_profit}"
        if order_id:
            data["Order ID"] = order_id[:16] + "..." if len(order_id) > 16 else order_id
        
        notification = Notification(
            type=NotificationType.ORDER_PLACED,
            title=f"Order Placed: {symbol}",
            message=f"{side} {order_type} order for {volume} lots at {entry_price}",
            broker=broker,
            symbol=symbol,
            data=data
        )
        return self.notify(notification)
    
    def notify_order_expired(
        self,
        broker: str,
        symbol: str,
        order_id: str,
        reason: str = "Timeout"
    ) -> int:
        """Convenience method for order expired notifications"""
        notification = Notification(
            type=NotificationType.ORDER_EXPIRED,
            title=f"Order Expired: {symbol}",
            message=f"Order {order_id[:16]}... expired. Reason: {reason}",
            broker=broker,
            symbol=symbol,
            data={"Order ID": order_id, "Reason": reason}
        )
        return self.notify(notification)
    
    def notify_error(
        self,
        broker: str,
        message: str,
        error_details: Optional[str] = None
    ) -> int:
        """Convenience method for error notifications"""
        data = {}
        if error_details:
            data["Details"] = error_details
        
        notification = Notification(
            type=NotificationType.ERROR,
            title="Trading Error",
            message=message,
            broker=broker,
            data=data if data else None
        )
        return self.notify(notification)


# Global notification service instance
_notification_service: Optional[NotificationService] = None


def get_notification_service(config: Optional[dict] = None) -> NotificationService:
    """Get or create the global notification service"""
    global _notification_service
    
    if _notification_service is None:
        if config is None:
            from config import get_config
            config = get_config().notifications.model_dump()
        _notification_service = NotificationService(config)
    
    return _notification_service
