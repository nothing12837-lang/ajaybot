"""
Telegram monitor utilities for AjayBot
"""
import asyncio
import logging
import aiohttp

logger = logging.getLogger("telegram_monitor")

# Telegram config - will be set from settings
_bot_token = ""
_chat_id = ""
_enabled = False


async def init_telegram():
    """Initialize telegram - called by monitor agent"""
    global _enabled
    from bot.config import get_settings
    settings = get_settings()
    global _bot_token, _chat_id
    _bot_token = settings.telegram.bot_token
    _chat_id = settings.telegram.chat_id
    _enabled = settings.telegram.enabled and bool(_bot_token)
    if _enabled:
        logger.info("Telegram monitor initialized")
    else:
        logger.warning("Telegram not configured (missing bot_token)")


async def send_alert(message: str, alert_type: str = "info"):
    """Send alert to Telegram"""
    if not _enabled or not _bot_token or not _chat_id:
        return
    
    url = f"https://api.telegram.org/bot{_bot_token}/sendMessage"
    payload = {
        "chat_id": _chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning(f"Telegram send failed: {resp.status} - {text}")
                else:
                    logger.debug(f"Telegram alert sent: {alert_type}")
    except Exception as e:
        logger.error(f"Telegram send error: {e}")


async def shutdown_telegram():
    """Shutdown telegram - nothing to clean up for bot API"""
    logger.info("Telegram monitor shutdown")