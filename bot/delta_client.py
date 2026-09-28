"""
Delta Exchange India API Client - REST and WebSocket
Based on Delta Exchange API v2
"""
import asyncio
import aiohttp
import hmac
import hashlib
import time
import json
import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Ticker:
    symbol: str
    mark_price: float
    index_price: float
    bid: float
    ask: float
    volume_24h: float
    timestamp: int


class DeltaClient:
    """Async REST client for Delta Exchange India"""

    def __init__(self, config):
        self.config = config
        self.base_url = config.delta.base_url.rstrip('/')
        self.api_key = config.delta.api_key
        self.api_secret = config.delta.api_secret
        self.session: Optional[aiohttp.ClientSession] = None
        self._initialized = False

    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self.session = aiohttp.ClientSession(timeout=timeout)
        self._initialized = True

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    def _sign_request(self, method: str, endpoint: str, payload: str = "") -> Dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        message = f"{timestamp}{method.upper()}{endpoint}{payload}"
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        return {
            'api-key': self.api_key,
            'timestamp': timestamp,
            'signature': signature,
            'Content-Type': 'application/json',
        }

    async def _request(self, method: str, endpoint: str, params: Dict = None, data: Dict = None) -> Any:
        await self._ensure_session()
        url = f"{self.base_url}{endpoint}"

        if data is not None:
            payload = json.dumps(data)
        else:
            payload = ""

        headers = self._sign_request(method, endpoint, payload)

        try:
            if method.upper() == 'GET':
                async with self.session.get(url, params=params, headers=headers) as resp:
                    result = await resp.json()
            elif method.upper() == 'POST':
                async with self.session.post(url, data=payload, headers=headers) as resp:
                    result = await resp.json()
            elif method.upper() == 'DELETE':
                async with self.session.delete(url, headers=headers) as resp:
                    result = await resp.json()
            else:
                raise ValueError(f"Unsupported method: {method}")

            if 'result' not in result and 'error' in result:
                raise Exception(f"API Error: {result.get('error', 'Unknown')}")

            return result.get('result', result)
        except aiohttp.ClientError as e:
            logger.error(f"Request failed: {e}")
            raise

    # Public endpoints
    async def get_products(self) -> List[Dict]:
        return await self._request('GET', '/v2/products')

    async def get_tickers(self, symbols: List[str] = None) -> List[Dict]:
        params = {}
        if symbols:
            params['symbol'] = ','.join(symbols)
        return await self._request('GET', '/v2/tickers', params=params)

    async def get_candles(self, symbol: str, resolution: str, start: int, end: int = None, limit: int = 500) -> List[Candle]:
        params = {
            'symbol': symbol,
            'resolution': resolution,
            'start': start,
            'limit': limit
        }
        if end:
            params['end'] = end

        data = await self._request('GET', '/v2/history/candles', params=params)
        candles = []
        for c in data:
            candles.append(Candle(
                timestamp=c['time'],
                open=float(c['open']),
                high=float(c['high']),
                low=float(c['low']),
                close=float(c['close']),
                volume=float(c['volume'])
            ))
        return candles

    async def get_l2_orderbook(self, symbol: str, depth: int = 20) -> Dict:
        params = {'symbol': symbol, 'depth': depth}
        return await self._request('GET', '/v2/l2orderbook', params=params)

    # Private endpoints (require API key)
    async def place_order(self, symbol: str, side: str, size: float, order_type: str = 'market',
                          price: float = None, stop_loss: float = None, take_profit: float = None) -> Dict:
        data = {
            'product_id': self._get_product_id(symbol),
            'side': side.lower(),
            'size': size,
            'order_type': order_type.lower(),
        }
        if price:
            data['limit_price'] = price
        if stop_loss:
            data['stop_price'] = stop_loss
        if take_profit:
            data['take_profit'] = take_profit

        return await self._request('POST', '/v2/orders', data=data)

    async def cancel_order(self, order_id: str) -> Dict:
        return await self._request('DELETE', f'/v2/orders/{order_id}')

    async def get_positions(self) -> List[Dict]:
        return await self._request('GET', '/v2/positions')

    async def get_wallet_balance(self, asset: str = 'USDT') -> float:
        data = await self._request('GET', '/v2/wallet/balances')
        for bal in data:
            if bal['asset_symbol'] == asset:
                return float(bal['available_balance'])
        return 0.0

    def _get_product_id(self, symbol: str) -> int:
        product_map = {
            'BTCUSD': 27,
            'ETHUSD': 3136,
            'SOLUSD': 14823,
            'DOGEUSD': 14745,
            'XRPUSD': 14969,
            'DOGSUSD': 50122,
            'AVAXUSD': 14830,
        }
        return product_map.get(symbol, 27)


class PublicCandleWS:
    """WebSocket client for public candle data"""

    def __init__(self, symbols: List[str], resolutions: List[str],
                 on_candle: Callable[[str, str, Candle], Any]):
        self.symbols = symbols
        self.resolutions = resolutions
        self.on_candle = on_candle
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.running = False
        self._reconnect_delay = 5

    async def connect(self):
        self.running = True
        url = "wss://socket.india.delta.exchange"

        while self.running:
            try:
                if self.session is None or self.session.closed:
                    timeout = aiohttp.ClientTimeout(total=30, connect=10)
                    self.session = aiohttp.ClientSession(timeout=timeout)

                async with self.session.ws_connect(url, heartbeat=30) as ws:
                    self.ws = ws
                    logger.info(f"WebSocket connected to {url}")
                    await self._subscribe()

                    async for msg in ws:
                        if not self.running:
                            break
                        await self._handle_message(msg)

            except Exception as e:
                logger.warning(f"WebSocket error: {e}, reconnecting in {self._reconnect_delay}s")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 1.5, 60)

    async def _subscribe(self):
        channels = [f"candles_{res}_{sym}" for sym in self.symbols for res in self.resolutions]
        logger.info(f"Subscribing to {len(channels)} candle channels: {channels}")
        await self.ws.send_json({
            'type': 'subscribe',
            'payload': {'channels': channels}
        })

    async def _handle_message(self, msg):
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            logger.info(f"WS candle message: {data}")  # DEBUG

            channel = data.get('channel', '')
            payload = data.get('payload', {})

            if channel.startswith('candles_'):
                if self.on_candle:
                    parts = channel.split('_')
                    if len(parts) >= 3:
                        resolution = parts[1]
                        symbol = '_'.join(parts[2:])
                        candle = Candle(
                            timestamp=payload['time'],
                            open=payload['open'],
                            high=payload['high'],
                            low=payload['low'],
                            close=payload['close'],
                            volume=payload['volume'],
                        )
                        await self.on_candle(symbol, resolution, candle)

            elif data.get('type') == 'subscribed':
                logger.info(f"WebSocket subscribed: {data}")

            elif data.get('type') == 'error':
                logger.warning(f"WebSocket error: {data}")

    async def stop(self):
        self.running = False
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()


class PublicTickerWS:
    """WebSocket client for real-time mark_price/ticker updates from Delta Exchange."""

    def __init__(self, symbols: List[str], on_ticker: Callable[[str, Ticker], Any]):
        self.symbols = symbols
        self.on_ticker = on_ticker
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.running = False
        self._reconnect_delay = 5

    async def connect(self):
        self.running = True
        url = "wss://socket.india.delta.exchange"

        while self.running:
            try:
                if self.session is None or self.session.closed:
                    timeout = aiohttp.ClientTimeout(total=30, connect=10)
                    self.session = aiohttp.ClientSession(timeout=timeout)

                async with self.session.ws_connect(url, heartbeat=30) as ws:
                    self.ws = ws
                    logger.info(f"WebSocket connected to {url}")
                    await self._subscribe()

                    async for msg in ws:
                        if not self.running:
                            break
                        await self._handle_message(msg)

            except Exception as e:
                logger.warning(f"WebSocket error: {e}, reconnecting in {self._reconnect_delay}s")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 1.5, 60)

    async def _subscribe(self):
        channels = [f"tickers_{sym}" for sym in self.symbols]
        logger.info(f"Subscribing to {len(channels)} ticker channels: {channels}")
        await self.ws.send_json({
            'type': 'subscribe',
            'payload': {'channels': channels}
        })

    async def _handle_message(self, msg):
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            logger.info(f"WS ticker message: {data}")  # DEBUG

            channel = data.get('channel', '')
            payload = data.get('payload', {})

            if channel.startswith('tickers_'):
                if self.on_ticker:
                    symbol = channel.replace('tickers_', '')
                    ticker = Ticker(
                        symbol=symbol,
                        mark_price=float(payload.get('mark_price', 0)),
                        index_price=float(payload.get('index_price', 0)),
                        funding_rate=float(payload.get('funding_rate', 0)),
                        next_funding_time=int(payload.get('next_funding_time', 0)),
                        open_interest=float(payload.get('open_interest', 0)),
                        volume_24h=float(payload.get('volume_24h', 0)),
                        bid=float(payload.get('bid_price', 0)),
                        ask=float(payload.get('ask_price', 0)),
                        spread=0,
                        timestamp=int(payload.get('timestamp', time.time() * 1000)),
                    )
                    ticker.spread = ticker.ask - ticker.bid if ticker.ask > ticker.bid > 0 else 0
                    if asyncio.iscoroutinefunction(self.on_ticker):
                        await self.on_ticker(symbol, ticker)
                    else:
                        self.on_ticker(symbol, ticker)

            elif data.get('type') == 'subscribed':
                logger.info(f"WebSocket subscribed: {data}")

            elif data.get('type') == 'error':
                logger.warning(f"WebSocket error: {data}")

    async def stop(self):
        self.running = False
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()


async def create_client(config, private: bool = False) -> DeltaClient:
    client = DeltaClient(config)
    if private and not config.delta.api_key:
        raise ValueError("API key required for private client")
    return client


async def create_public_ws(symbols: List[str], resolutions: List[str],
                           on_candle=None, on_ticker=None) -> tuple:
    """Create both candle and ticker WebSocket clients"""
    candle_ws = PublicCandleWS(symbols, resolutions, on_candle)
    ticker_ws = PublicTickerWS(symbols, on_ticker)
    await candle_ws.connect()
    await ticker_ws.connect()
    return candle_ws, ticker_ws