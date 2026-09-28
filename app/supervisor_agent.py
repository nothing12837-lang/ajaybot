#!/usr/bin/env python3
"""
Supervisor Agent - Manages AjayBot (trading) + MoneyPrinterTurbo (YouTube/IG)
Runs independently, checks both services health, restarts on failure, sends Telegram alerts.
"""

import asyncio
import aiohttp
import logging
import sys
import os
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Any

# Add paths
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import existing telegram module
from bot.telegram_monitor import init_telegram, send_alert, shutdown_telegram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("supervisor_agent")

AJAYBOT_URL = "http://localhost:8081"
MPT_URL = "http://localhost:8082"
CHECK_INTERVAL = 30  # seconds
RESTART_COOLDOWN = 300  # 5 minutes between restarts per service

class SupervisorAgent:
    def __init__(self):
        self.running = False
        self.telegram_enabled = False
        self.ajaybot_process = None
        self.mpt_process = None
        self.last_restart = {"ajaybot": 0, "mpt": 0}
        self.ajaybot_health_history = []
        self.mpt_health_history = []
        self.start_time = datetime.now(timezone.utc)
        
    async def start(self):
        # Load config for telegram
        from bot.config import load_config, get_settings
        load_config("config/config.yaml")
        settings = get_settings()
        
        self.telegram_enabled = settings.telegram.enabled and bool(settings.telegram.bot_token)
        if self.telegram_enabled:
            await init_telegram()
            logger.info("Supervisor Telegram initialized")
        else:
            logger.warning("Supervisor: Telegram not configured")
            
        self.running = True
        await self.send_startup_alert()
        await self.monitor_loop()
        
    async def send_startup_alert(self):
        if not self.telegram_enabled:
            return
        msg = (
            f"🤖 <b>SUPERVISOR AGENT STARTED</b>\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"Monitoring: AjayBot (port 8081) + MoneyPrinterTurbo (port 8082)\n"
            f"Auto-restart: Enabled (5min cooldown)\n"
        )
        await send_alert(msg, "info")
        
    async def check_ajaybot(self) -> Dict[str, Any]:
        """Check AjayBot health via API"""
        issues = []
        data = {}
        
        try:
            async with aiohttp.ClientSession() as session:
                # Status endpoint
                async with session.get(f"{AJAYBOT_URL}/api/status", 
                                       timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                    else:
                        issues.append(f"Status API HTTP {resp.status}")
                        return {"healthy": False, "issues": issues, "data": {}}
                        
                # Positions endpoint
                async with session.get(f"{AJAYBOT_URL}/api/positions",
                                       timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data["positions"] = await resp.json()
                        
        except asyncio.TimeoutError:
            issues.append("API timeout")
        except aiohttp.ClientConnectorError:
            issues.append("Connection refused - bot may be down")
        except Exception as e:
            issues.append(f"API error: {e}")
            
        if not issues:
            # Health checks
            if data.get("state") != "running":
                issues.append(f"Bot state: {data.get('state')}")
                
            drawdown = data.get("drawdown", 0)
            if drawdown > 0.15:
                issues.append(f"High drawdown: {drawdown:.1%}")
                
            consec = data.get("consecutive_losses", 0)
            if consec >= 3:
                issues.append(f"Consecutive losses: {consec}")
                
            equity = data.get("equity", 0)
            if equity < 50:  # 25% of $200
                issues.append(f"Critical equity: ${equity:,.2f}")
                
            last_heartbeat = data.get("last_heartbeat", 0)
            if time.time() - last_heartbeat > 300:
                issues.append(f"Stale heartbeat: {time.time() - last_heartbeat:.0f}s ago")
                
        return {
            "healthy": len(issues) == 0,
            "issues": issues,
            "data": data
        }
        
    async def check_mpt(self) -> Dict[str, Any]:
        """Check MoneyPrinterTurbo health via API"""
        issues = []
        data = {}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{MPT_URL}/ping",
                                       timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        # Response is JSON string "pong" (with quotes), accept both
                        clean_text = text.strip().strip('"')
                        if clean_text != "pong":
                            issues.append(f"Unexpected ping response: {text}")
                    else:
                        issues.append(f"Ping HTTP {resp.status}")
                        
                # Check tasks endpoint for stuck tasks
                async with session.get(f"{MPT_URL}/api/v1/tasks",
                                       timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    logger.info(f"MPT tasks response: {resp.status}")
                    if resp.status == 200:
                        result = await resp.json()
                        logger.info(f"MPT tasks result: {result}")
                        data["tasks"] = result.get("data", {}).get("tasks", [])
                        
        except asyncio.TimeoutError:
            issues.append("MPT API timeout")
        except aiohttp.ClientConnectorError:
            issues.append("MPT connection refused - service may be down")
        except Exception as e:
            logger.error(f"MPT check exception: {e}")
            issues.append(f"MPT API error: {e}")
            
        return {
            "healthy": len(issues) == 0,
            "issues": issues,
            "data": data
        }
        
    async def restart_ajaybot(self, reason: str):
        """Restart AjayBot"""
        now = time.time()
        if now - self.last_restart["ajaybot"] < RESTART_COOLDOWN:
            logger.warning(f"AjayBot restart skipped - cooldown ({RESTART_COOLDOWN}s)")
            return False
            
        self.last_restart["ajaybot"] = now
        logger.warning(f"RESTARTING AJAYBOT: {reason}")
        
        # Kill existing
        import subprocess
        subprocess.run(["taskkill", "/F", "/IM", "python.exe", "/FI", "WINDOWTITLE eq *AjayBot*"],
                       capture_output=True)
        subprocess.run(["pkill", "-f", "main.py"], capture_output=True)
        await asyncio.sleep(3)
        
        # Start new
        import subprocess
        self.ajaybot_process = subprocess.Popen(
            [sys.executable, "main.py"],
            cwd="/c/Users/ajay kumar/Downloads/AjayBot",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        if self.telegram_enabled:
            await send_alert(f"🔄 <b>AJAYBOT RESTARTED</b>\nReason: {reason}", "warning")
        return True
        
    async def restart_mpt(self, reason: str):
        """Restart MoneyPrinterTurbo"""
        now = time.time()
        if now - self.last_restart["mpt"] < RESTART_COOLDOWN:
            logger.warning(f"MPT restart skipped - cooldown ({RESTART_COOLDOWN}s)")
            return False
            
        self.last_restart["mpt"] = now
        logger.warning(f"RESTARTING MPT: {reason}")
        
        import subprocess
        subprocess.run(["taskkill", "/F", "/IM", "python.exe", "/FI", "WINDOWTITLE eq *MoneyPrinter*"],
                       capture_output=True)
        subprocess.run(["pkill", "-f", "MoneyPrinterTurbo.*main.py"], capture_output=True)
        await asyncio.sleep(3)
        
        import subprocess
        self.mpt_process = subprocess.Popen(
            [sys.executable, "main.py"],
            cwd="/c/Users/ajay kumar/Downloads/MoneyPrinterTurbo",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        if self.telegram_enabled:
            await send_alert(f"🔄 <b>MONEYPRINTER RESTARTED</b>\nReason: {reason}", "warning")
        return True
        
    async def send_alert_if_needed(self, service: str, health: Dict):
        if not self.telegram_enabled:
            return
            
        from bot.config import get_settings
        settings = get_settings()
        if not settings.telegram.alert_risk:
            return
            
        if not health["healthy"]:
            issues = health["issues"]
            issue_types = []
            for issue in issues:
                if "equity" in issue.lower():
                    issue_types.append("Low equity")
                elif "drawdown" in issue.lower():
                    issue_types.append("High drawdown")
                elif "consecutive" in issue.lower():
                    issue_types.append("Consecutive losses")
                elif "heartbeat" in issue.lower() or "connection" in issue.lower():
                    issue_types.append("Service down")
                else:
                    issue_types.append(issue)
                    
            issue_key = f"{service}:{','.join(sorted(set(issue_types)))}"
            if issue_key not in self.alerted_issues:
                self.alerted_issues.add(issue_key)
                msg = f"⚠️ <b>{service.upper()} HEALTH ISSUE</b>\n" + "\n".join(f"• {i}" for i in issues)
                await send_alert(msg, "warning")
        else:
            # Clear alerted issues when healthy
            keys_to_remove = [k for k in self.alerted_issues if k.startswith(service + ":")]
            for k in keys_to_remove:
                self.alerted_issues.discard(k)
                
    async def monitor_loop(self):
        self.alerted_issues = set()
        consecutive_failures = {"ajaybot": 0, "mpt": 0}
        
        while self.running:
            try:
                # Check both services in parallel
                ajay_health, mpt_health = await asyncio.gather(
                    self.check_ajaybot(),
                    self.check_mpt(),
                    return_exceptions=True
                )
                
                if isinstance(ajay_health, Exception):
                    ajay_health = {"healthy": False, "issues": [f"Check crashed: {ajay_health}"], "data": {}}
                if isinstance(mpt_health, Exception):
                    mpt_health = {"healthy": False, "issues": [f"Check crashed: {mpt_health}"], "data": {}}
                    
                # Log status
                ajay_status = "✓" if ajay_health["healthy"] else "✗"
                mpt_status = "✓" if mpt_health["healthy"] else "✗"
                logger.info(f"Health: AjayBot {ajay_status} | MPT {mpt_status}")
                
                # Track consecutive failures
                if ajay_health["healthy"]:
                    consecutive_failures["ajaybot"] = 0
                else:
                    consecutive_failures["ajaybot"] += 1
                    if consecutive_failures["ajaybot"] >= 2:
                        await self.restart_ajaybot(f"{consecutive_failures['ajaybot']} consecutive failures: {', '.join(ajay_health['issues'])}")
                        consecutive_failures["ajaybot"] = 0
                        
                if mpt_health["healthy"]:
                    consecutive_failures["mpt"] = 0
                else:
                    consecutive_failures["mpt"] += 1
                    if consecutive_failures["mpt"] >= 2:
                        await self.restart_mpt(f"{consecutive_failures['mpt']} consecutive failures: {', '.join(mpt_health['issues'])}")
                        consecutive_failures["mpt"] = 0
                        
                # Send alerts
                await self.send_alert_if_needed("ajaybot", ajay_health)
                await self.send_alert_if_needed("mpt", mpt_health)
                
                # Heartbeat alert every 4 hours
                uptime = (datetime.now(timezone.utc) - self.start_time).total_seconds()
                if int(uptime) % 14400 == 0 and uptime > 100:
                    if self.telegram_enabled:
                        await send_alert(
                            f"💓 <b>SUPERVISOR HEARTBEAT</b>\n"
                            f"Uptime: {uptime/3600:.1f}h\n"
                            f"AjayBot: {'OK' if ajay_health['healthy'] else 'ISSUES'}\n"
                            f"MPT: {'OK' if mpt_health['healthy'] else 'ISSUES'}",
                            "info"
                        )
                        
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                
            await asyncio.sleep(CHECK_INTERVAL)

async def main():
    supervisor = SupervisorAgent()
    await supervisor.start()

if __name__ == "__main__":
    asyncio.run(main())