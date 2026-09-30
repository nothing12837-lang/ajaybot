#!/usr/bin/env python3
"""
Persistent AjayBot Monitoring Agent
Runs independently, checks bot health, sends Telegram alerts ONLY for:
- Trade events (open/close/partial)
- Risk/critical alerts
- Health issues (bot down, high drawdown, etc.) - ONCE per issue, not spam
"""
import asyncio
import aiohttp
import logging
import sys
import os
from datetime import datetime, timezone

# Add bot directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.config import load_config, get_settings

# Try to import telegram functions if available
try:
    from bot.telegram_monitor import init_telegram, send_alert, shutdown_telegram
    HAS_TELEGRAM = True
except ImportError:
    HAS_TELEGRAM = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("monitor_agent")

WEBUI_URL = "http://localhost:8081"
CHECK_INTERVAL = 60  # seconds

class MonitorAgent:
    def __init__(self):
        self.running = False
        self.last_status = None
        self.start_time = datetime.now(timezone.utc)
        self.starting_equity = None
        self.alerted_issues = set()  # Track which issues we've already alerted
        
    async def start(self):
        load_config("config/config.yaml")
        settings = get_settings()
        # Capture starting equity from config
        self.starting_equity = settings.risk.paper_equity
        logger.info(f"Monitor starting equity baseline: ${self.starting_equity}")
        
        self.telegram_enabled = settings.telegram.enabled and settings.telegram.bot_token
        if self.telegram_enabled and HAS_TELEGRAM:
            await init_telegram()
            logger.info("Telegram initialized for monitor agent")
        else:
            logger.warning("Telegram not configured or module missing, running without alerts")
      
        self.running = True
        await self.send_startup_alert()
        await self.monitor_loop()
      
    async def send_startup_alert(self):
        if not self.telegram_enabled or not HAS_TELEGRAM:
            return
        settings = get_settings()
        msg = (
            f"🤖 <b>AJAYBOT MONITOR AGENT STARTED</b>\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"Mode: {settings.mode}\n"
            f"Symbols: {', '.join([s.symbol for s in settings.symbols])}\n"
            f"Starting Equity: ${self.starting_equity:,.2f}\n"
            f"WebUI: {WEBUI_URL}"
        )
        await send_alert(msg, "info")
      
    async def fetch_bot_status(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{WEBUI_URL}/api/status", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            logger.warning(f"Failed to fetch bot status: {e}")
        return None
      
    async def check_bot_health(self):
        status = await self.fetch_bot_status()
        if not status:
            return {"healthy": False, "reason": "Bot API unreachable"}
          
        # Check various health indicators
        issues = []
      
        # Check if bot is running
        if status.get("state") != "running":
            issues.append(f"Bot state: {status.get('state')}")
          
        # Check drawdown (relative to peak)
        drawdown = status.get("drawdown", 0)
        if drawdown > 0.15:  # 15% max DD
            issues.append(f"High drawdown: {drawdown:.1%}")
          
        # Check consecutive losses
        cons_losses = status.get("consecutive_losses", 0)
        if cons_losses >= 3:
            issues.append(f"Consecutive losses: {cons_losses}")
          
        # Check equity (relative to starting equity)
        equity = status.get("equity", 0)
        if self.starting_equity and equity < self.starting_equity * 0.85:  # 15% below starting
            issues.append(f"Low equity: ${equity:,.2f} (started at ${self.starting_equity:,.2f})")
          
        # Check heartbeat freshness
        last_heartbeat = status.get("last_heartbeat", 0)
        import time
        if time.time() - last_heartbeat > 300:  # 5 minutes
            issues.append(f"Stale heartbeat: {time.time() - last_heartbeat:.0f}s ago")
          
        return {
            "healthy": len(issues) == 0,
            "issues": issues,
            "status": status
        }
      
    async def send_alert_if_needed(self, health):
        settings = get_settings()
        if not self.telegram_enabled or not HAS_TELEGRAM or not settings.telegram.alert_risk:
            return

        if not health["healthy"]:
            issues = health["issues"]
            # Create a fingerprint of issue TYPES only (ignore changing values like exact equity)
            issue_types = []
            for issue in issues:
                if "Low equity" in issue:
                    issue_types.append("Low equity")
                elif "High drawdown" in issue:
                    issue_types.append("High drawdown")
                elif "Consecutive losses" in issue:
                    issue_types.append("Consecutive losses")
                elif "Bot state" in issue:
                    issue_types.append("Bot state")
                elif "Stale heartbeat" in issue:
                    issue_types.append("Stale heartbeat")
                else:
                    issue_types.append(issue)

            issue_fingerprint = tuple(sorted(issue_types))

            # Only alert if this is a NEW issue TYPE set
            if issue_fingerprint not in self.alerted_issues:
                self.alerted_issues.add(issue_fingerprint)
                msg = (
                    f"⚠️ <b>HEALTH CHECK ALERT</b>\n"
                    f"Issues detected:\n" + "\n".join(f"• {issue}" for issue in issues)
                )
                await send_alert(msg, "warning")
            else:
                # Already alerted for this issue type, just log
                logger.info(f"Health issue type already alerted: {issue_types}")
        else:
            # Bot healthy - clear alerted issues if we had any
            if self.alerted_issues:
                self.alerted_issues.clear()
                logger.info("Bot recovered - cleared alerted issues")
          
    async def monitor_loop(self):
        while self.running:
            try:
                health = await self.check_bot_health()
              
                if health["healthy"]:
                    logger.info(f"Bot healthy: equity=${health['status'].get('equity',0):,.2f}, positions={health['status'].get('positions',0)}")
                else:
                    logger.warning(f"Bot issues: {health['issues']}")
                    await self.send_alert_if_needed(health)
                  
                # Detect significant changes - only alert on position count change
                if self.last_status and health["healthy"]:
                    old = self.last_status
                    new = health["status"]
                  
                    # Position count changed (trade opened/closed)
                    if old.get("positions") != new.get("positions"):
                        msg = f"📈 <b>POSITIONS CHANGED</b>\nOld: {old.get('positions')} → New: {new.get('positions')}"
                        await send_alert(msg, "trade")
                      
                self.last_status = health["status"] if health["healthy"] else self.last_status
              
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
              
            await asyncio.sleep(CHECK_INTERVAL)
          
    async def stop(self):
        self.running = False
        if self.telegram_enabled and HAS_TELEGRAM:
            msg = f"🤖 <b>AJAYBOT MONITOR AGENT STOPPED</b>\nTime: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
            await send_alert(msg, "info")
            await shutdown_telegram()
        logger.info("Monitor agent stopped")

async def main():
    monitor = MonitorAgent()
    try:
        await monitor.start()
    except KeyboardInterrupt:
        await monitor.stop()
    except Exception as e:
        logger.error(f"Monitor agent crashed: {e}")
        await monitor.stop()

if __name__ == "__main__":
    asyncio.run(main())