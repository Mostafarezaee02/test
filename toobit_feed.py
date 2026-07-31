"""
اتصال به وب‌سوکت توبیت و دریافت قیمت لحظه‌ای (bookTicker) برای هر سیمبل درخواستی
"""

import asyncio
import json
import logging
import time

import websockets

from config import TOOBIT_WS_URL

log = logging.getLogger("toobit_feed")


class ToobitPriceFeed:
    def __init__(self):
        self.prices: dict[str, float] = {}
        self._subscribed: set[str] = set()
        self._ws = None
        self._stop = False

    async def subscribe(self, ws_symbol: str):
        """درخواست اشتراک روی یک سیمبل (اگه قبلا نبود)"""
        if ws_symbol in self._subscribed:
            return
        self._subscribed.add(ws_symbol)
        if self._ws is not None:
            await self._send_subscribe(ws_symbol)

    async def unsubscribe(self, ws_symbol: str):
        if ws_symbol not in self._subscribed:
            return
        self._subscribed.discard(ws_symbol)
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps({
                    "symbol": ws_symbol,
                    "topic": "bookTicker",
                    "event": "cancel",
                }))
            except Exception:
                pass

    async def _send_subscribe(self, ws_symbol: str):
        msg = {
            "symbol": ws_symbol,
            "topic": "bookTicker",
            "event": "sub",
        }
        await self._ws.send(json.dumps(msg))

    async def run(self):
        """حلقه اصلی: وصل میشه، دیتا میگیره، اگه قطع شد دوباره وصل میشه"""
        backoff = 1
        while not self._stop:
            try:
                async with websockets.connect(
                    TOOBIT_WS_URL, ping_interval=None, close_timeout=5
                ) as ws:
                    self._ws = ws
                    log.info("به وب‌سوکت توبیت وصل شد")
                    backoff = 1

                    # اشتراک مجدد روی همه سیمبل‌های قبلی (مثلا بعد از قطعی)
                    for sym in list(self._subscribed):
                        await self._send_subscribe(sym)

                    heartbeat_task = asyncio.create_task(self._heartbeat(ws))
                    try:
                        async for raw in ws:
                            self._handle_message(raw)
                    finally:
                        heartbeat_task.cancel()
            except Exception as e:
                log.warning(f"اتصال وب‌سوکت قطع شد، تلاش مجدد تا {backoff}s: {e}")
                self._ws = None
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _heartbeat(self, ws):
        """هر ۱۵ ثانیه پینگ میفرسته تا سرور کانکشن رو نبنده (سرور تا ۵ دقیقه بی‌پاسخی وصل می‌مونه)"""
        try:
            while True:
                await asyncio.sleep(15)
                await ws.send(json.dumps({"ping": int(time.time() * 1000)}))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.debug(f"heartbeat error: {e}")

    def _handle_message(self, raw):
        try:
            data = json.loads(raw)
        except Exception:
            return

        if "pong" in data:
            return

        topic = data.get("topic")
        if topic == "bookTicker":
            d = data.get("data", {})
            symbol = d.get("s")
            try:
                bid = float(d.get("b"))
                ask = float(d.get("a"))
            except (TypeError, ValueError):
                return
            if symbol:
                self.prices[symbol] = (bid + ask) / 2

    def get_price(self, ws_symbol: str):
        return self.prices.get(ws_symbol)

    def stop(self):
        self._stop = True
