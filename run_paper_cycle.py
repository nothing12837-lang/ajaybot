"""
Run a single paper trading cycle for AjayBot in GitHub Actions or cloud cron.
Initializes engine, loads history, processes cycle, and saves state to disk.
"""
import asyncio
import logging
import sys
from pathlib import Path

# Ensure root directory is on sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from bot.config import load_config
from bot.bot import AjayBot, candle_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
logger = logging.getLogger("paper_cycle")


async def main():
    logger.info("Initializing AjayBot for paper trading cycle...")
    config_path = BASE_DIR / "config" / "config.yaml"
    config = load_config(str(config_path))
    bot = AjayBot(config)

    logger.info("Starting Paper Engine...")
    await bot.engine.start()

    logger.info("Loading recent candle history for symbols...")
    for sym_config in config.symbols:
        symbol = sym_config.symbol
        resolutions = [sym_config.resolution]
        if sym_config.htf_resolution:
            resolutions.append(sym_config.htf_resolution)

        for res in resolutions:
            try:
                await candle_store.ensure_history(
                    symbol, res, min(sym_config.lookback, 50), bot.engine.client
                )
            except Exception as e:
                logger.warning(f"Could not load history for {symbol} {res}: {e}")

    logger.info("Processing trading cycle...")
    try:
        await bot._process_cycle()
        logger.info("Trading cycle completed successfully.")
    except Exception as e:
        logger.error(f"Error during trading cycle: {e}")
        raise
    finally:
        bot._save_state()
        if bot.engine.client and hasattr(bot.engine.client, "close"):
            try:
                await bot.engine.client.close()
            except Exception:
                pass

    logger.info("Paper cycle finished cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
