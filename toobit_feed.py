"""
دریافت قیمت لحظه‌ای فیوچرز — Binance USDT-M WebSocket
(توبیت سرورهای Railway رو بلاک می‌کنه — Binance کار می‌کنه و قیمتش برای پرپچوال‌های
اصلی تقریباً با توبیت یکیه)

نسخه‌ی جدید برخلاف قبل به‌ازای هر نماد جدید کل اتصال رو قطع/وصل نمی‌کنه — یک اتصال
پایدار به /stream نگه می‌داره و نمادها رو با پیام‌های SUBSCRIBE / UNSUBSCRIBE
اضافه/حذف می‌کنه. این یعنی افزودن یه سیگنال جدید هیچ تاخیری تو دریافت قیمت
سیگنال‌های دیگه ایجاد نمی‌کنه.
"""

import asyncio
import json
import logging
import time

import websockets

log = logging.getLogger("price_feed")

BINANCE_WS_URL = "wss://fstream.binance.com/stream"
STALE_AFTER_SECONDS = 20  # اگه بیشتر از این مدت آپدیتی نیومد، قیمت "نامعتبر" در نظر گرفته می‌شه


def to_binance_stream(ws_symbol: str) -> str:
    """ETH-SWAP-USDT  ->  ethusdt@bookTicker"""
    base = ws_symbol.replace("-SWAP-USDT", "").replace("-", "").lower()
    return f"{base}usdt@bookTicker"


class ToobitPriceFeed:
    def __init__(self):
        self.prices: dict[str, float] = {}          # ws_symbol -> قیمت میانگین bid/ask
        self._last_update: dict[str, float] = {}     # ws_symbol -> زمان آخرین آپدیت (monotonic)
        self._subscribed: set[str] = set()
        self._ws = None
        self._stop = False
        self._req_id = 0
        self._lock = asyncio.Lock()

    async def subscribe(self, ws_symbol: str):
        async with self._lock:
            if ws_symbol in self._subscribed:
                return
            self._subscribed.add(ws_symbol)
            ws = self._ws
        if ws is not None:
            await self._send(ws, "SUBSCRIBE", [to_binance_stream(ws_symbol)])

    async def unsubscribe(self, ws_symbol: str):
        async with self._lock:
            if ws_symbol not in self._subscribed:
                return
            self._subscribed.discard(ws_symbol)
            ws = self._ws
        if ws is not None:
            await self._send(ws, "UNSUBSCRIBE", [to_binance_stream(ws_symbol)])

    async def _send(self, ws, method: str, params: list[str]):
        self._req_id += 1
        try:
            await ws.send(json.dumps({"method": method, "params": params, "id": self._req_id}))
        except Exception as e:
            log.warning(f"خطا در ارسال {method}: {e}")

    async def run(self):
        """اتصال پایدار به Binance؛ در صورت قطعی با backoff نمایی دوباره وصل می‌شه"""
        backoff = 1
        while not self._stop:
            try:
                async with websockets.connect(
                    BINANCE_WS_URL, ping_interval=20, ping_timeout=10, close_timeout=5
                ) as ws:
                    self._ws = ws
                    backoff = 1
                    async with self._lock:
                        subs = list(self._subscribed)
                    if subs:
                        await self._send(ws, "SUBSCRIBE", [to_binance_stream(s) for s in subs])
                    log.info(f"✅ به Binance Futures وصل شد | {len(subs)} نماد فعال")

                    async for raw in ws:
                        self._handle(raw)

            except Exception as e:
                log.warning(f"اتصال قطع شد، {backoff}s صبر می‌کنیم و دوباره تلاش می‌کنیم: {e}")
            finally:
                self._ws = None

            if not self._stop:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def _handle(self, raw: str):
        try:
            msg = json.loads(raw)
        except Exception:
            return

        d = msg.get("data", msg)  # combined stream یه لایه data اضافه داره

        symbol_bn = d.get("s", "").upper()
        if not symbol_bn:
            return
        try:
            bid = float(d["b"])
            ask = float(d["a"])
        except (KeyError, TypeError, ValueError):
            return
        if bid <= 0 or ask <= 0:
            return

        price = (bid + ask) / 2
        base = symbol_bn[:-4] if symbol_bn.endswith("USDT") else symbol_bn
        ws_key = f"{base}-SWAP-USDT"
        self.prices[ws_key] = price
        self._last_update[ws_key] = time.monotonic()

    def get_price(self, ws_symbol: str):
        """قیمت رو برمی‌گردونه؛ اگه خیلی وقته آپدیت نشده None می‌ده (به‌جای قیمت باطل)"""
        price = self.prices.get(ws_symbol)
        if price is None:
            return None
        ts = self._last_update.get(ws_symbol, 0)
        if time.monotonic() - ts > STALE_AFTER_SECONDS:
            return None
        return price

    def is_stale(self, ws_symbol: str) -> bool:
        ts = self._last_update.get(ws_symbol)
        return ts is None or (time.monotonic() - ts > STALE_AFTER_SECONDS)

    def stop(self):
        self._stop = True
