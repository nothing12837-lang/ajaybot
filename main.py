"""
AjayBot Main Entry Point
"""
import asyncio
import logging

from bot.bot import AjayBot
from bot.config import load_config, get_settings
from webui.trading_app import app, set_bot_instance

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
logger = logging.getLogger("ajaybot")


async def run_bot():
    logger.info("Initializing AjayBot...")
    config = load_config("config/config.yaml")
    bot = AjayBot(config)
    set_bot_instance(bot)
    await bot.start()


async def run_server():
    settings = get_settings()
    logger.info(f"Starting Web UI Dashboard on port {settings.webui.port}...")
    import uvicorn
    config = uvicorn.Config(app, host=settings.webui.host, port=settings.webui.port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    # Load config first, before starting bot or server
    config = load_config("config/config.yaml")
    logger.info(f"Config loaded: paper_equity={config.risk.paper_equity}, data_dir={config.data_dir}")

    bot = AjayBot(config)
    set_bot_instance(bot)

    await asyncio.gather(bot.start(), run_server())


if __name__ == "__main__":
    asyncio.run(main())