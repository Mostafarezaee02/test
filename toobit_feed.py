"""
دریافت قیمت لحظه‌ای از Binance Futures WebSocket
(توبیت سرورهای Railway رو بلاک می‌کنه — Binance کار می‌کنه و قیمتش تقریباً یکیه)
"""

import asyncio
import json
import logging

import websockets

log = logging.getLogger("price_feed")

BINANCE_WS_BASE = "wss://fstream.binance.com/ws"


def to_binance_symbol(ws_symbol: str) -> str:
    """
    ETH-SWAP-USDT  →  ethusdt   (فرمت Binance Futures)
    BTC-SWAP-USDT  →  btcusdt
    """
    base = ws_symbol.replace("-SWAP-USDT", "").replace("-", "").lower()
    return base + "usdt"


class ToobitPriceFeed:
    def __init__(self):
        self.prices: dict[str, float] = {}      # ws_symbol (ETH-SWAP-USDT) -> price
        self._subscribed: set[str] = set()
        self._stop = False

    async def subscribe(self, ws_symbol: str):
        self._subscribed.add(ws_symbol)
        # اگه حلقه در حال اجراست، ری‌استارت خودکار انجام میشه

    async def unsubscribe(self, ws_symbol: str):
        self._subscribed.discard(ws_symbol)

    async def run(self):
        """حلقه اصلی — برای هر مجموعه سیمبل‌ها یه اتصال combined stream می‌زنه"""
        backoff = 1
        while not self._stop:
            subs = list(self._subscribed)
            if not subs:
                await asyncio.sleep(1)
                continue

            streams = "/".join(
                f"{to_binance_symbol(s)}@bookTicker" for s in subs
            )
            url = f"{BINANCE_WS_BASE}/{streams}"

            try:
                async with websockets.connect(url, ping_interval=20, close_timeout=5) as ws:
                    log.info(f"به Binance Futures وصل شد | {streams}")
                    backoff = 1
                    async for raw in ws:
                        self._handle(raw)

                        # اگه سیمبل جدیدی اضافه شده، ری‌کانکت کن تا سابسکرایب بشه
                        if set(self._subscribed) != set(subs):
                            break

            except Exception as e:
                log.warning(f"اتصال قطع شد، {backoff}s صبر: {e}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def _handle(self, raw: str):
        try:
            d = json.loads(raw)
        except Exception:
            return

        # combined stream یه لایه data داره، single stream نداره
        if "data" in d:
            d = d["data"]

        symbol_bn = d.get("s", "").upper()   # مثلاً ETHUSDT
        try:
            bid = float(d["b"])
            ask = float(d["a"])
        except (KeyError, TypeError, ValueError):
            return

        price = (bid + ask) / 2

        # ذخیره با فرمت ws_symbol (ETH-SWAP-USDT) تا بقیه کد تغییر نکنه
        base = symbol_bn.replace("USDT", "")
        ws_key = f"{base}-SWAP-USDT"
        self.prices[ws_key] = price

    def get_price(self, ws_symbol: str):
        return self.prices.get(ws_symbol)

    def stop(self):
        self._stop = True
