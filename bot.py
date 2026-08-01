"""
ربات سیگنال‌دهی زنده — رابط کاربری کامل دکمه‌ای

دستورات:
  /signal       شروع ثبت سیگنال
  /list         لیست سیگنال‌های باز
  /close        بستن سیگنال
  /setsl        تغییر حد ضرر
  /settp        تغییر حد سود
  /cancel       لغو در هر مرحله
"""

import asyncio
import logging
import time
import uuid

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter, TimedOut
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters,
)

import config
import storage
from signal_model import Signal, format_signal_message
from toobit_feed import ToobitPriceFeed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("bot")

SYMBOL, SYMBOL_CUSTOM, SIDE, LEVERAGE, LEVERAGE_CUSTOM, ENTRY, SL, TP, CONFIRM = range(9)

signals: dict[str, Signal] = {}
feed = ToobitPriceFeed()

# ─── نمادها و اهرم‌های پرکاربرد ───────────────────────────────────────────
QUICK_SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "XRP", "SUI", "1000SHIB"]
QUICK_LEVERAGES = [5, 10, 20, 25, 50]

# ─── کمکی‌ها ───────────────────────────────────────────────────────────────

def only_owner(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = (update.effective_user.id if update.effective_user else None)
        if uid != config.OWNER_ID:
            if update.callback_query:
                await update.callback_query.answer("⛔️ دسترسی ندارید.", show_alert=True)
            elif update.message:
                await update.message.reply_text("⛔️ فقط مالک ربات می‌تونه دستور بده.")
            return ConversationHandler.END
        return await func(update, context)
    return wrapper

def to_ws_symbol(s: str) -> str:
    s = s.upper().replace("USDT","").strip("-").strip()
    return f"{s}-SWAP-USDT"

def to_display_symbol(s: str) -> str:
    s = s.upper().replace("USDT","").strip("-").strip()
    return f"{s}USDT"

def glass_sep():
    return "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

def make_symbol_keyboard():
    rows = []
    row = []
    for i, sym in enumerate(QUICK_SYMBOLS):
        row.append(InlineKeyboardButton(f"🪙 {sym}", callback_data=f"sym_{sym}"))
        if len(row) == 3:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("✏️  نماد دیگه‌ای دارم", callback_data="sym_custom")])
    rows.append([InlineKeyboardButton("❌  لغو", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)

def make_side_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📈  LONG",  callback_data="side_LONG"),
            InlineKeyboardButton("📉  SHORT", callback_data="side_SHORT"),
        ],
        [InlineKeyboardButton("❌  لغو", callback_data="cancel")],
    ])

def make_leverage_keyboard():
    rows = [[
        InlineKeyboardButton(f"⚡️ {lev}x", callback_data=f"lev_{lev}")
        for lev in QUICK_LEVERAGES
    ]]
    rows.append([InlineKeyboardButton("✏️  اهرم دیگه‌ای دارم", callback_data="lev_custom")])
    rows.append([InlineKeyboardButton("❌  لغو", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)

def make_skip_keyboard(skip_cb: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭  رد کردن", callback_data=skip_cb)],
        [InlineKeyboardButton("❌  لغو",    callback_data="cancel")],
    ])

def make_confirm_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅  ثبت و پست در کانال", callback_data="confirm_yes"),
            InlineKeyboardButton("❌  لغو",               callback_data="confirm_no"),
        ]
    ])

def draft_text(d: dict) -> str:
    side_fa = "لانگ 📈" if d.get("side") == "LONG" else "شورت 📉"
    sl  = d.get("stop_loss")
    tp  = d.get("take_profit")
    return (
        f"✦ <b>خلاصه سیگنال</b>\n"
        f"{glass_sep()}\n"
        f"🪙  نماد    »  <code>{d.get('symbol','—')}</code>\n"
        f"📊  جهت     »  {side_fa}\n"
        f"⚡️  اهرم    »  <code>{d.get('leverage','—')}x</code>\n"
        f"🎯  ورود    »  <code>{d.get('entry','—')}</code>\n"
        f"🛑  حد ضرر  »  <code>{sl if sl else 'ندارد'}</code>\n"
        f"🏁  حد سود  »  <code>{tp if tp else 'ندارد'}</code>\n"
        f"{glass_sep()}"
    )

# ─── مراحل ConversationHandler ──────────────────────────────────────────────

@only_owner
async def cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "✦ <b>ثبت سیگنال جدید</b>\n"
        f"{glass_sep()}\n"
        "🪙  <b>نماد ارز رو انتخاب کن:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=make_symbol_keyboard(),
    )
    return SYMBOL


async def step_symbol_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        await q.edit_message_text("❌ سیگنال لغو شد.")
        return ConversationHandler.END
    if q.data == "sym_custom":
        await q.edit_message_text(
            "✏️  <b>نماد رو تایپ کن:</b>\n\nمثلاً: <code>PEPE</code>  یا  <code>WIF</code>",
            parse_mode=ParseMode.HTML,
        )
        return SYMBOL_CUSTOM

    sym = q.data.replace("sym_", "")
    context.user_data["ws_symbol"] = to_ws_symbol(sym)
    context.user_data["symbol"]    = to_display_symbol(sym)
    await q.edit_message_text(
        f"✅  نماد: <code>{context.user_data['symbol']}</code>\n\n"
        f"{glass_sep()}\n"
        "📊  <b>جهت معامله رو انتخاب کن:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=make_side_keyboard(),
    )
    return SIDE


async def step_symbol_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    context.user_data["ws_symbol"] = to_ws_symbol(raw)
    context.user_data["symbol"]    = to_display_symbol(raw)
    await update.message.reply_text(
        f"✅  نماد: <code>{context.user_data['symbol']}</code>\n\n"
        f"{glass_sep()}\n"
        "📊  <b>جهت معامله رو انتخاب کن:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=make_side_keyboard(),
    )
    return SIDE


async def step_side(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        await q.edit_message_text("❌ سیگنال لغو شد.")
        return ConversationHandler.END
    side = q.data.replace("side_", "")
    context.user_data["side"] = side
    side_fa = "لانگ 📈" if side == "LONG" else "شورت 📉"
    await q.edit_message_text(
        f"✅  جهت: {side_fa}\n\n"
        f"{glass_sep()}\n"
        "⚡️  <b>اهرم رو انتخاب کن:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=make_leverage_keyboard(),
    )
    return LEVERAGE


async def step_leverage_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        await q.edit_message_text("❌ سیگنال لغو شد.")
        return ConversationHandler.END
    if q.data == "lev_custom":
        await q.edit_message_text(
            "✏️  <b>اهرم دلخواه رو تایپ کن:</b>\n\nمثلاً: <code>15</code>",
            parse_mode=ParseMode.HTML,
        )
        return LEVERAGE_CUSTOM
    lev = float(q.data.replace("lev_", ""))
    context.user_data["leverage"] = lev
    await q.edit_message_text(
        f"✅  اهرم: <code>{lev}x</code>\n\n"
        f"{glass_sep()}\n"
        "🎯  <b>نقطه ورود رو تایپ کن:</b>\n\n"
        "مثلاً: <code>65800</code>",
        parse_mode=ParseMode.HTML,
    )
    return ENTRY


async def step_leverage_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        lev = float(update.message.text.strip())
        if lev <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ عدد معتبر وارد کن (مثلاً 15)")
        return LEVERAGE_CUSTOM
    context.user_data["leverage"] = lev
    await update.message.reply_text(
        f"✅  اهرم: <code>{lev}x</code>\n\n"
        f"{glass_sep()}\n"
        "🎯  <b>نقطه ورود رو تایپ کن:</b>\n\n"
        "مثلاً: <code>65800</code>",
        parse_mode=ParseMode.HTML,
    )
    return ENTRY


async def step_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        entry = float(update.message.text.strip().replace(",",""))
        if entry <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ قیمت معتبر وارد کن (مثلاً 65800)")
        return ENTRY
    context.user_data["entry"] = entry
    await update.message.reply_text(
        f"✅  ورود: <code>{entry}</code>\n\n"
        f"{glass_sep()}\n"
        "🛑  <b>حد ضرر رو تایپ کن یا رد کن:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=make_skip_keyboard("sl_skip"),
    )
    return SL


async def step_sl_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sl = float(update.message.text.strip().replace(",",""))
        if sl <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ قیمت معتبر وارد کن یا دکمه رد کردن رو بزن.")
        return SL
    context.user_data["stop_loss"] = sl
    await update.message.reply_text(
        f"✅  حد ضرر: <code>{sl}</code>\n\n"
        f"{glass_sep()}\n"
        "🏁  <b>حد سود رو تایپ کن یا رد کن:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=make_skip_keyboard("tp_skip"),
    )
    return TP


async def step_sl_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        await q.edit_message_text("❌ سیگنال لغو شد.")
        return ConversationHandler.END
    context.user_data["stop_loss"] = None
    await q.edit_message_text(
        f"⏭  حد ضرر: ندارد\n\n"
        f"{glass_sep()}\n"
        "🏁  <b>حد سود رو تایپ کن یا رد کن:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=make_skip_keyboard("tp_skip"),
    )
    return TP


async def step_tp_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tp = float(update.message.text.strip().replace(",",""))
        if tp <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ قیمت معتبر وارد کن یا دکمه رد کردن رو بزن.")
        return TP
    context.user_data["take_profit"] = tp
    await update.message.reply_text(
        f"✅  حد سود: <code>{tp}</code>\n\n"
        f"{draft_text(context.user_data)}\n\n"
        "<b>ثبت کنم؟</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=make_confirm_keyboard(),
    )
    return CONFIRM


async def step_tp_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        await q.edit_message_text("❌ سیگنال لغو شد.")
        return ConversationHandler.END
    context.user_data["take_profit"] = None
    await q.edit_message_text(
        f"⏭  حد سود: ندارد\n\n"
        f"{draft_text(context.user_data)}\n\n"
        "<b>ثبت کنم؟</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=make_confirm_keyboard(),
    )
    return CONFIRM


async def step_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "confirm_no":
        await q.edit_message_text("❌ سیگنال لغو شد.")
        return ConversationHandler.END

    d = context.user_data
    base = d["symbol"].replace("USDT","").lower()
    sig_id = f"{base}-{uuid.uuid4().hex[:5]}"

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

    await q.edit_message_text(
        f"✅  سیگنال ثبت شد و در کانال پست شد!\n"
        f"{glass_sep()}\n"
        f"🆔  شناسه: <code>{sig_id}</code>\n\n"
        f"برای حد ضرر/سود بعدی:\n"
        f"<code>/setsl {sig_id} قیمت</code>\n"
        f"<code>/settp {sig_id} قیمت</code>",
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


@only_owner
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ عملیات لغو شد.")
    return ConversationHandler.END

# ─── دستورات مدیریتی ────────────────────────────────────────────────────────

@only_owner
async def cmd_setsl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("فرمت: /setsl <id> <price>")
        return
    sig = signals.get(args[0])
    if not sig:
        await update.message.reply_text("❌ سیگنالی با این شناسه پیدا نشد.")
        return
    try:
        sig.stop_loss = float(args[1].replace(",",""))
    except ValueError:
        await update.message.reply_text("قیمت نامعتبره.")
        return
    storage.save_signals(signals)
    await update.message.reply_text(f"✅ حد ضرر <code>{sig.id}</code> روی <code>{sig.stop_loss}</code> تنظیم شد.", parse_mode=ParseMode.HTML)


@only_owner
async def cmd_settp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("فرمت: /settp <id> <price>")
        return
    sig = signals.get(args[0])
    if not sig:
        await update.message.reply_text("❌ سیگنالی با این شناسه پیدا نشد.")
        return
    try:
        sig.take_profit = float(args[1].replace(",",""))
    except ValueError:
        await update.message.reply_text("قیمت نامعتبره.")
        return
    storage.save_signals(signals)
    await update.message.reply_text(f"✅ حد سود <code>{sig.id}</code> روی <code>{sig.take_profit}</code> تنظیم شد.", parse_mode=ParseMode.HTML)


@only_owner
async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("فرمت: /close <id> [price]")
        return
    sig = signals.get(args[0])
    if not sig:
        await update.message.reply_text("❌ سیگنالی با این شناسه پیدا نشد.")
        return
    if sig.status != "OPEN":
        await update.message.reply_text("این سیگنال از قبل بسته شده.")
        return
    price = float(args[1].replace(",","")) if len(args) > 1 else feed.get_price(sig.ws_symbol)
    sig.status = "CLOSED"
    sig.closed_price = price
    sig.closed_at = time.time()
    storage.save_signals(signals)
    await update_channel_message(context, sig, price)
    await update.message.reply_text(f"⏹ سیگنال <code>{sig.id}</code> بسته شد.", parse_mode=ParseMode.HTML)


@only_owner
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    open_sigs = [s for s in signals.values() if s.status == "OPEN"]
    if not open_sigs:
        await update.message.reply_text("سیگنال باز فعالی وجود نداره.")
        return
    lines = [f"✦ <b>سیگنال‌های باز</b>\n{glass_sep()}"]
    for s in open_sigs:
        price = feed.get_price(s.ws_symbol)
        pnl = s.pnl_percent(price) if price else 0.0
        mood = "🟢" if pnl > 0 else ("🔴" if pnl < 0 else "⚪️")
        lines.append(
            f"{mood}  <code>{s.id}</code>\n"
            f"    {s.symbol}  {s.side}  {s.leverage}x  →  {pnl:+.2f}%"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

# ─── آپدیت زنده ─────────────────────────────────────────────────────────────

async def update_channel_message(context_or_app, sig: Signal, price):
    text = format_signal_message(sig, price)
    if text == sig.last_sent_text:
        return
    bot = context_or_app.bot if hasattr(context_or_app, "bot") else context_or_app
    try:
        await bot.edit_message_text(
            chat_id=sig.chat_id, message_id=sig.message_id,
            text=text, parse_mode=ParseMode.HTML,
        )
        sig.last_sent_text = text
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after)
    except BadRequest as e:
        if "not modified" in str(e).lower():
            sig.last_sent_text = text
        else:
            log.warning(f"خطای ادیت {sig.id}: {e}")
    except (TimedOut, Exception):
        pass


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

# ─── main ────────────────────────────────────────────────────────────────────

def main():
    if config.BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        raise SystemExit("لطفا config.py رو پر کن.")

    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("signal", cmd_signal)],
        states={
            SYMBOL:          [CallbackQueryHandler(step_symbol_btn,    pattern="^(sym_|cancel)")],
            SYMBOL_CUSTOM:   [MessageHandler(filters.TEXT & ~filters.COMMAND, step_symbol_custom)],
            SIDE:            [CallbackQueryHandler(step_side,           pattern="^(side_|cancel)")],
            LEVERAGE:        [CallbackQueryHandler(step_leverage_btn,   pattern="^(lev_|cancel)")],
            LEVERAGE_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_leverage_custom)],
            ENTRY:           [MessageHandler(filters.TEXT & ~filters.COMMAND, step_entry)],
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
    app.add_handler(CommandHandler("setsl",  cmd_setsl))
    app.add_handler(CommandHandler("settp",  cmd_settp))
    app.add_handler(CommandHandler("close",  cmd_close))
    app.add_handler(CommandHandler("list",   cmd_list))

    log.info("ربات در حال اجراست...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
