"""
ربات تلگرام سیگنال‌دهی زنده

دستورات:
  /signal       شروع ثبت سیگنال مرحله به مرحله (توصیه‌شده)
  /setsl <id> <price>
  /settp <id> <price>
  /close <id> [price]
  /list
  /cancel       لغو ثبت سیگنال در هر مرحله
"""

import asyncio
import logging
import time
import uuid

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter, TimedOut
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

import config
import storage
from signal_model import Signal, format_signal_message
from toobit_feed import ToobitPriceFeed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")

# مراحل ConversationHandler
SYMBOL, SIDE, LEVERAGE, ENTRY, SL, TP, CONFIRM = range(7)

signals: dict[str, Signal] = {}
feed = ToobitPriceFeed()


# ---------------------------------------------------------------------------
# کمکی‌ها
# ---------------------------------------------------------------------------

def only_owner(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if uid != config.OWNER_ID:
            if update.message:
                await update.message.reply_text("⛔️ فقط مالک ربات می‌تونه دستور بده.")
            elif update.callback_query:
                await update.callback_query.answer("⛔️ دسترسی ندارید.", show_alert=True)
            return ConversationHandler.END
        return await func(update, context)
    return wrapper


def to_ws_symbol(s: str) -> str:
    s = s.upper().replace("USDT", "").strip("-").strip()
    return f"{s}-SWAP-USDT"


def to_display_symbol(s: str) -> str:
    s = s.upper().replace("USDT", "").strip("-").strip()
    return f"{s}USDT"


def draft_summary(ctx_data: dict) -> str:
    side_fa = "لانگ 🟩" if ctx_data.get("side") == "LONG" else "شورت 🟥"
    sl = ctx_data.get("stop_loss")
    tp = ctx_data.get("take_profit")
    lines = [
        "📋 <b>خلاصه سیگنال:</b>",
        "",
        f"🪙 نماد: <code>{ctx_data.get('symbol', '-')}</code>",
        f"📊 جهت: {side_fa}",
        f"⚙️ اهرم: <code>{ctx_data.get('leverage', '-')}x</code>",
        f"🎯 نقطه ورود: <code>{ctx_data.get('entry', '-')}</code>",
        f"🛑 حد ضرر: <code>{sl if sl else 'ندارد'}</code>",
        f"🏁 حد سود: <code>{tp if tp else 'ندارد'}</code>",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# شروع مکالمه
# ---------------------------------------------------------------------------

@only_owner
async def cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🔍 <b>نماد ارز رو بنویس:</b>\n\nمثلاً: <code>BTC</code> یا <code>ETH</code> یا <code>SOL</code>",
        parse_mode=ParseMode.HTML,
    )
    return SYMBOL


async def step_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    ws_sym = to_ws_symbol(raw)
    display_sym = to_display_symbol(raw)
    context.user_data["ws_symbol"] = ws_sym
    context.user_data["symbol"] = display_sym

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("LONG 🟢", callback_data="side_LONG"),
            InlineKeyboardButton("SHORT 🔴", callback_data="side_SHORT"),
        ],
        [InlineKeyboardButton("❌ لغو", callback_data="cancel")],
    ])
    await update.message.reply_text(
        f"✅ نماد: <code>{display_sym}</code>\n\n📊 <b>جهت معامله رو انتخاب کن:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    return SIDE


async def step_side(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ ثبت سیگنال لغو شد.")
        return ConversationHandler.END

    side = query.data.replace("side_", "")
    context.user_data["side"] = side
    side_fa = "لانگ 🟢" if side == "LONG" else "شورت 🔴"

    await query.edit_message_text(
        f"✅ جهت: {side_fa}\n\n⚙️ <b>اهرم رو وارد کن:</b>\n\nمثلاً: <code>10</code>",
        parse_mode=ParseMode.HTML,
    )
    return LEVERAGE


async def step_leverage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        lev = float(update.message.text.strip())
        if lev <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ عدد معتبر وارد کن (مثلاً 10)")
        return LEVERAGE

    context.user_data["leverage"] = lev
    await update.message.reply_text(
        f"✅ اهرم: <code>{lev}x</code>\n\n🎯 <b>نقطه ورود رو وارد کن:</b>\n\nمثلاً: <code>1800</code>",
        parse_mode=ParseMode.HTML,
    )
    return ENTRY


async def step_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        entry = float(update.message.text.strip())
        if entry <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ قیمت معتبر وارد کن (مثلاً 1800)")
        return ENTRY

    context.user_data["entry"] = entry

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ رد کردن (بدون حد ضرر)", callback_data="sl_skip")],
        [InlineKeyboardButton("❌ لغو کل", callback_data="cancel")],
    ])
    await update.message.reply_text(
        f"✅ نقطه ورود: <code>{entry}</code>\n\n🛑 <b>حد ضرر رو وارد کن یا رد کن:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    return SL


async def step_sl_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sl = float(update.message.text.strip())
        if sl <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ قیمت معتبر وارد کن یا دکمه رد کردن رو بزن.")
        return SL

    context.user_data["stop_loss"] = sl
    return await _ask_tp(update.message, context)


async def step_sl_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ ثبت سیگنال لغو شد.")
        return ConversationHandler.END

    context.user_data["stop_loss"] = None
    await query.edit_message_text("⏭ حد ضرر: ندارد")
    return await _ask_tp(query.message, context)


async def _ask_tp(message, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ رد کردن (بدون حد سود)", callback_data="tp_skip")],
        [InlineKeyboardButton("❌ لغو کل", callback_data="cancel")],
    ])
    await message.reply_text(
        "🏁 <b>حد سود رو وارد کن یا رد کن:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    return TP


async def step_tp_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tp = float(update.message.text.strip())
        if tp <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ قیمت معتبر وارد کن یا دکمه رد کردن رو بزن.")
        return TP

    context.user_data["take_profit"] = tp
    return await _ask_confirm(update.message, context)


async def step_tp_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ ثبت سیگنال لغو شد.")
        return ConversationHandler.END

    context.user_data["take_profit"] = None
    await query.edit_message_text("⏭ حد سود: ندارد")
    return await _ask_confirm(query.message, context)


async def _ask_confirm(message, context):
    summary = draft_summary(context.user_data)
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ ثبت و پست در کانال", callback_data="confirm_yes"),
            InlineKeyboardButton("❌ لغو", callback_data="confirm_no"),
        ]
    ])
    await message.reply_text(
        summary + "\n\n<b>ثبت کنم؟</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    return CONFIRM


async def step_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_no":
        await query.edit_message_text("❌ سیگنال لغو شد.")
        return ConversationHandler.END

    d = context.user_data
    sig_id = f"{d['symbol'].replace('USDT','').lower()}-{uuid.uuid4().hex[:5]}"

    sig = Signal(
        id=sig_id,
        symbol=d["symbol"],
        ws_symbol=d["ws_symbol"],
        side=d["side"],
        leverage=d["leverage"],
        entry=d["entry"],
        stop_loss=d.get("stop_loss"),
        take_profit=d.get("take_profit"),
        chat_id=config.CHANNEL_ID,
    )

    await feed.subscribe(sig.ws_symbol)

    text = format_signal_message(sig, price=sig.entry)
    msg = await context.bot.send_message(
        chat_id=config.CHANNEL_ID,
        text=text,
        parse_mode=ParseMode.HTML,
    )
    sig.message_id = msg.message_id
    sig.last_sent_text = text
    signals[sig_id] = sig
    storage.save_signals(signals)

    await query.edit_message_text(
        f"✅ سیگنال ثبت شد و در کانال پست شد!\n\n🆔 شناسه: <code>{sig_id}</code>",
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


@only_owner
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ ثبت سیگنال لغو شد.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# سایر دستورات
# ---------------------------------------------------------------------------

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
        lines.append(f"• <code>{s.id}</code> — {s.symbol} {s.side} {s.leverage}x — {pnl:+.2f}%")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------------------
# آپدیت زنده پیام کانال
# ---------------------------------------------------------------------------

async def update_channel_message(context_or_app, sig: Signal, price):
    text = format_signal_message(sig, price)
    if text == sig.last_sent_text:
        return
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
        log.warning(f"فلود کنترل تلگرام، {e.retry_after}s صبر")
        await asyncio.sleep(e.retry_after)
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            sig.last_sent_text = text
        else:
            log.warning(f"خطای ادیت {sig.id}: {e}")
    except TimedOut:
        pass
    except Exception as e:
        log.warning(f"خطا در ادیت {sig.id}: {e}")


async def price_update_loop(app: Application):
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
            log.exception(f"خطا در حلقه آپدیت: {e}")
        await asyncio.sleep(config.UPDATE_INTERVAL_SECONDS)


async def post_init(app: Application):
    global signals
    signals = storage.load_signals()
    for sig in signals.values():
        if sig.status == "OPEN":
            await feed.subscribe(sig.ws_symbol)
    asyncio.create_task(feed.run())
    asyncio.create_task(price_update_loop(app))
    log.info("ربات آماده شد ✅")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    if config.BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        raise SystemExit("لطفا config.py رو پر کن.")

    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("signal", cmd_signal)],
        states={
            SYMBOL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, step_symbol)],
            SIDE:     [CallbackQueryHandler(step_side, pattern="^(side_|cancel)")],
            LEVERAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_leverage)],
            ENTRY:    [MessageHandler(filters.TEXT & ~filters.COMMAND, step_entry)],
            SL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_sl_text),
                CallbackQueryHandler(step_sl_skip, pattern="^(sl_skip|cancel)"),
            ],
            TP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_tp_text),
                CallbackQueryHandler(step_tp_skip, pattern="^(tp_skip|cancel)"),
            ],
            CONFIRM: [CallbackQueryHandler(step_confirm, pattern="^confirm_")],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("setsl", cmd_setsl))
    app.add_handler(CommandHandler("settp", cmd_settp))
    app.add_handler(CommandHandler("close", cmd_close))
    app.add_handler(CommandHandler("list", cmd_list))

    log.info("ربات در حال اجراست...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
