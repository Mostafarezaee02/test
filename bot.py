"""
ربات تلگرام سیگنال‌دهی زنده - قیمت از توبیت میاد و پیام کانال زنده آپدیت میشه

نحوه استفاده (فقط OWNER_ID اجازه داره):

  /newsignal ETH LONG 10 1800              -> بدون حد ضرر
  /newsignal ETH LONG 10 1800 1750         -> با حد ضرر
  /newsignal ETH LONG 10 1800 1750 1950    -> با حد ضرر و حد سود

  /setsl <id> <price>       تنظیم/تغییر حد ضرر
  /settp <id> <price>       تنظیم/تغییر حد سود
  /close <id> [price]       بستن دستی سیگنال (اگه قیمت ندی، از آخرین قیمت لحظه‌ای استفاده میشه)
  /list                     لیست سیگنال‌های باز
"""

import asyncio
import logging
import time
import uuid

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter, TimedOut
from telegram.ext import Application, CommandHandler, ContextTypes

import config
import storage
from signal_model import Signal, format_signal_message
from toobit_feed import ToobitPriceFeed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")

# state: id -> Signal
signals: dict[str, Signal] = {}
feed = ToobitPriceFeed()


def only_owner(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user is None or update.effective_user.id != config.OWNER_ID:
            await update.message.reply_text("⛔️ این ربات فقط برای مالک قابل استفادس.")
            return
        return await func(update, context)
    return wrapper


def to_ws_symbol(short_symbol: str) -> str:
    """ETH -> ETH-SWAP-USDT (فرمت فیوچرز توبیت)"""
    s = short_symbol.upper().replace("USDT", "").strip("-")
    return f"{s}-SWAP-USDT"


def to_display_symbol(short_symbol: str) -> str:
    s = short_symbol.upper().replace("USDT", "").strip("-")
    return f"{s}USDT"


# ---------------------------------------------------------------------------
# دستورات
# ---------------------------------------------------------------------------

@only_owner
async def cmd_newsignal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 4:
        await update.message.reply_text(
            "فرمت درست:\n"
            "/newsignal SYMBOL LONG|SHORT LEVERAGE ENTRY [SL] [TP]\n\n"
            "مثال:\n/newsignal ETH LONG 10 1800 1750"
        )
        return

    try:
        raw_symbol = args[0]
        side = args[1].upper()
        leverage = float(args[2])
        entry = float(args[3])
        stop_loss = float(args[4]) if len(args) > 4 else None
        take_profit = float(args[5]) if len(args) > 5 else None
    except ValueError:
        await update.message.reply_text("مقادیر عددی (اهرم/قیمت) نامعتبره.")
        return

    if side not in ("LONG", "SHORT"):
        await update.message.reply_text("جهت معامله باید LONG یا SHORT باشه.")
        return

    ws_symbol = to_ws_symbol(raw_symbol)
    display_symbol = to_display_symbol(raw_symbol)
    sig_id = f"{raw_symbol.lower()}-{uuid.uuid4().hex[:5]}"

    sig = Signal(
        id=sig_id,
        symbol=display_symbol,
        ws_symbol=ws_symbol,
        side=side,
        leverage=leverage,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        chat_id=config.CHANNEL_ID,
    )

    await feed.subscribe(ws_symbol)

    text = format_signal_message(sig, price=entry)
    msg = await context.bot.send_message(
        chat_id=config.CHANNEL_ID,
        text=text,
        parse_mode=ParseMode.HTML,
    )
    sig.message_id = msg.message_id
    sig.last_sent_text = text

    signals[sig_id] = sig
    storage.save_signals(signals)

    await update.message.reply_text(f"✅ سیگنال ثبت شد و در کانال پست شد.\nشناسه: {sig_id}")


@only_owner
async def cmd_setsl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("فرمت: /setsl <id> <price>")
        return
    sig = signals.get(args[0])
    if not sig:
        await update.message.reply_text("سیگنالی با این شناسه پیدا نشد.")
        return
    try:
        sig.stop_loss = float(args[1])
    except ValueError:
        await update.message.reply_text("قیمت نامعتبره.")
        return
    storage.save_signals(signals)
    await update.message.reply_text(f"✅ حد ضرر {sig.id} روی {sig.stop_loss} تنظیم شد.")


@only_owner
async def cmd_settp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("فرمت: /settp <id> <price>")
        return
    sig = signals.get(args[0])
    if not sig:
        await update.message.reply_text("سیگنالی با این شناسه پیدا نشد.")
        return
    try:
        sig.take_profit = float(args[1])
    except ValueError:
        await update.message.reply_text("قیمت نامعتبره.")
        return
    storage.save_signals(signals)
    await update.message.reply_text(f"✅ حد سود {sig.id} روی {sig.take_profit} تنظیم شد.")


@only_owner
async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("فرمت: /close <id> [price]")
        return
    sig = signals.get(args[0])
    if not sig:
        await update.message.reply_text("سیگنالی با این شناسه پیدا نشد.")
        return
    if sig.status != "OPEN":
        await update.message.reply_text("این سیگنال از قبل بسته شده.")
        return

    price = float(args[1]) if len(args) > 1 else feed.get_price(sig.ws_symbol)
    sig.status = "CLOSED"
    sig.closed_price = price
    sig.closed_at = time.time()
    storage.save_signals(signals)

    await update_channel_message(context, sig, price)
    await update.message.reply_text(f"⏹ سیگنال {sig.id} بسته شد.")


@only_owner
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    open_signals = [s for s in signals.values() if s.status == "OPEN"]
    if not open_signals:
        await update.message.reply_text("سیگنال باز فعالی وجود نداره.")
        return
    lines = []
    for s in open_signals:
        price = feed.get_price(s.ws_symbol)
        pnl = s.pnl_percent(price) if price else 0.0
        lines.append(f"• {s.id} — {s.symbol} {s.side} {s.leverage}x — {pnl:+.2f}%")
    await update.message.reply_text("\n".join(lines))


@only_owner
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(__doc__)


# ---------------------------------------------------------------------------
# آپدیت زنده‌ی پیام‌های کانال
# ---------------------------------------------------------------------------

async def update_channel_message(context_or_app, sig: Signal, price):
    """پیام کانال مربوط به این سیگنال رو ادیت می‌کنه (اگه متن تغییر کرده باشه)"""
    text = format_signal_message(sig, price)
    if text == sig.last_sent_text:
        return  # چیزی عوض نشده، ادیت الکی نزن

    bot = context_or_app.bot if hasattr(context_or_app, "bot") else context_or_app
    try:
        await bot.edit_message_text(
            chat_id=sig.chat_id,
            message_id=sig.message_id,
            text=text,
            parse_mode=ParseMode.HTML,
        )
        sig.last_sent_text = text
    except RetryAfter as e:
        log.warning(f"فلود کنترل تلگرام، {e.retry_after}s صبر می‌کنیم")
        await asyncio.sleep(e.retry_after)
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            sig.last_sent_text = text
        else:
            log.warning(f"خطای ادیت پیام برای {sig.id}: {e}")
    except TimedOut:
        pass
    except Exception as e:
        log.warning(f"خطای غیرمنتظره در ادیت پیام {sig.id}: {e}")


async def price_update_loop(app: Application):
    """هر UPDATE_INTERVAL_SECONDS ثانیه، همه سیگنال‌های باز رو با قیمت جدید آپدیت می‌کنه"""
    while True:
        try:
            for sig in list(signals.values()):
                if sig.status != "OPEN":
                    continue
                price = feed.get_price(sig.ws_symbol)
                if price is None:
                    continue

                hit = sig.check_sl_tp(price)
                if hit:
                    sig.status = hit
                    sig.closed_price = price
                    sig.closed_at = time.time()
                    storage.save_signals(signals)

                await update_channel_message(app, sig, price)
        except Exception as e:
            log.exception(f"خطا در حلقه آپدیت قیمت: {e}")

        await asyncio.sleep(config.UPDATE_INTERVAL_SECONDS)


async def post_init(app: Application):
    # بارگذاری سیگنال‌های ذخیره‌شده از اجرای قبلی
    global signals
    signals = storage.load_signals()
    for sig in signals.values():
        if sig.status == "OPEN":
            await feed.subscribe(sig.ws_symbol)

    asyncio.create_task(feed.run())
    asyncio.create_task(price_update_loop(app))
    log.info("ربات آماده شد و حلقه آپدیت قیمت شروع شد.")


def main():
    if config.BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        raise SystemExit("لطفا اول config.py رو با توکن و آیدی‌های واقعی پر کن.")

    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("newsignal", cmd_newsignal))
    app.add_handler(CommandHandler("setsl", cmd_setsl))
    app.add_handler(CommandHandler("settp", cmd_settp))
    app.add_handler(CommandHandler("close", cmd_close))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))

    log.info("ربات در حال اجراست...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
