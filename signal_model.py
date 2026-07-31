"""
مدل سیگنال + محاسبه سود/ضرر + قالب‌بندی پیام تلگرام
"""

import time
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Signal:
    id: str                      # شناسه یکتای سیگنال، مثلا eth-1
    symbol: str                  # نمایش داده شده، مثلا ETHUSDT
    ws_symbol: str                # سیمبل فیوچرز توبیت، مثلا ETH-SWAP-USDT
    side: str                    # LONG یا SHORT
    leverage: float
    entry: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    chat_id: Optional[int] = None
    message_id: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    status: str = "OPEN"          # OPEN, CLOSED, SL_HIT, TP_HIT
    closed_price: Optional[float] = None
    closed_at: Optional[float] = None
    last_sent_text: Optional[str] = None
    last_price_used: Optional[float] = None

    def pnl_percent(self, price: float) -> float:
        """درصد سود/ضرر با احتساب اهرم، نسبت به نقطه ورود"""
        if price is None or self.entry == 0:
            return 0.0
        change = (price - self.entry) / self.entry
        if self.side == "SHORT":
            change = -change
        return change * self.leverage * 100

    def check_sl_tp(self, price: float) -> Optional[str]:
        """اگه قیمت به حد ضرر یا حد سود خورده باشه، وضعیت رو برمیگردونه"""
        if price is None or self.status != "OPEN":
            return None
        if self.side == "LONG":
            if self.stop_loss is not None and price <= self.stop_loss:
                return "SL_HIT"
            if self.take_profit is not None and price >= self.take_profit:
                return "TP_HIT"
        else:  # SHORT
            if self.stop_loss is not None and price >= self.stop_loss:
                return "SL_HIT"
            if self.take_profit is not None and price <= self.take_profit:
                return "TP_HIT"
        return None

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        return Signal(**d)


def _fmt_num(n: float) -> str:
    if n is None:
        return "-"
    # حذف صفرهای اضافی ولی حفظ دقت معقول
    s = f"{n:,.6f}".rstrip("0").rstrip(".")
    return s


def format_signal_message(sig: Signal, price: Optional[float]) -> str:
    side_fa = "لانگ 🟩" if sig.side == "LONG" else "شورت 🟥"
    arrow = "📈" if sig.side == "LONG" else "📉"

    if sig.status == "OPEN":
        pnl = sig.pnl_percent(price) if price else 0.0
        if pnl > 0.0001:
            mood_emoji = "🟢"
            mood_text = "در سود"
        elif pnl < -0.0001:
            mood_emoji = "🔴"
            mood_text = "در ضرر"
        else:
            mood_emoji = "⚪️"
            mood_text = "نقطه سر به سر"

        lines = [
            f"{arrow} <b>سیگنال {sig.symbol}</b>  |  {side_fa}",
            "",
            f"⚙️ اهرم: <code>{sig.leverage}x</code>",
            f"🎯 نقطه ورود: <code>{_fmt_num(sig.entry)}</code>",
            f"💰 قیمت لحظه‌ای: <code>{_fmt_num(price) if price else '...'}</code>",
        ]
        if sig.stop_loss:
            lines.append(f"🛑 حد ضرر: <code>{_fmt_num(sig.stop_loss)}</code>")
        if sig.take_profit:
            lines.append(f"🏁 هدف سود: <code>{_fmt_num(sig.take_profit)}</code>")

        lines.append("")
        lines.append(f"{mood_emoji} وضعیت: <b>{mood_text} ({pnl:+.2f}%)</b>")
        lines.append("")
        lines.append(f"🕒 آخرین بروزرسانی: {time.strftime('%H:%M:%S')}")
        lines.append(f"🆔 <code>{sig.id}</code>")
        return "\n".join(lines)

    else:
        # سیگنال بسته شده (دستی، حد ضرر یا حد سود)
        final_price = sig.closed_price if sig.closed_price is not None else price
        pnl = sig.pnl_percent(final_price) if final_price else 0.0
        if sig.status == "SL_HIT":
            title = "🔴 حد ضرر فعال شد"
        elif sig.status == "TP_HIT":
            title = "✅ هدف سود محقق شد"
        else:
            title = "⏹ سیگنال بسته شد"

        lines = [
            f"{arrow} <b>سیگنال {sig.symbol}</b>  |  {side_fa}  |  <b>{title}</b>",
            "",
            f"⚙️ اهرم: <code>{sig.leverage}x</code>",
            f"🎯 نقطه ورود: <code>{_fmt_num(sig.entry)}</code>",
            f"🚪 قیمت خروج: <code>{_fmt_num(final_price)}</code>",
        ]
        lines.append("")
        result_emoji = "🟢" if pnl >= 0 else "🔴"
        lines.append(f"{result_emoji} نتیجه نهایی: <b>{pnl:+.2f}%</b>")
        lines.append("")
        lines.append(f"🕒 زمان بسته شدن: {time.strftime('%H:%M:%S')}")
        lines.append(f"🆔 <code>{sig.id}</code>")
        return "\n".join(lines)
