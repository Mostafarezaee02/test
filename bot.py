"""
ربات سیگنال‌دهی زنده — رابط کاربری کامل دکمه‌ای + جستجوی نماد + داشبورد زنده
"""

import asyncio
import logging
import time
import uuid
import urllib.request
import json as _json

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter, TimedOut
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters,
)

import config
import storage
import toobit_feed
from signal_model import Signal, format_signal_message
from toobit_feed import ToobitPriceFeed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("bot")

# مراحل ConversationHandler برای ثبت سیگنال
SYMBOL_MENU, SYMBOL_SEARCH, SIDE, LEVERAGE, LEVERAGE_CUSTOM, ENTRY, SL, TP, CONFIRM = range(9)

# مراحل ConversationHandler برای ست SL/TP از داشبورد
DB_AWAIT_SL, DB_AWAIT_TP = range(9, 11)

signals: dict[str, Signal] = {}
feed = ToobitPriceFeed()
ALL_SYMBOLS: list[str] = []

# داشبورد: شناسه پیام‌هایی که باید زنده آپدیت بشن
# ساختار: {"channel": (chat_id, message_id), "private": (chat_id, message_id)}
dashboard: dict[str, tuple] = {}

QUICK_SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "XRP", "SUI", "1000SHIB"]
QUICK_LEVERAGES = [5, 10, 20, 25, 50]
SEP = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

STATIC_SYMBOLS = sorted(set([
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "TRX", "TON", "AVAX", "SHIB", "1000SHIB",
    "DOT", "LINK", "MATIC", "LTC", "BCH", "UNI", "ATOM", "XLM", "ETC", "FIL", "APT", "ARB", "OP",
    "NEAR", "IMX", "VET", "HBAR", "GRT", "ALGO", "SAND", "MANA", "AXS", "THETA", "EOS", "AAVE",
    "MKR", "SNX", "COMP", "XTZ", "EGLD", "FLOW", "CHZ", "ENJ", "ZEC", "DASH", "XMR", "KSM",
    "RUNE", "1INCH", "SUSHI", "CRV", "YFI", "BAT", "ZIL", "IOTA", "NEO", "WAVES", "QTUM",
    "ICX", "ONT", "ZRX", "OMG", "KAVA", "BAND", "STORJ", "CTSI", "SKL", "CELR", "ANKR",
    "RSR", "OCEAN", "CVC", "DENT", "HOT", "WIN", "BTT", "STMX", "IOST", "DGB", "SC",
    "RVN", "XVG", "ZEN", "LSK", "ARK", "STRAX", "NANO", "XEM", "BTS", "STEEM", "GAS",
    "SUI", "SEI", "TIA", "INJ", "PYTH", "JTO", "JUP", "STRK", "WLD", "PEPE", "WIF", "BOME",
    "FLOKI", "BONK", "1000BONK", "1000PEPE", "1000FLOKI", "MEME", "ORDI", "SATS", "1000SATS",
    "RATS", "NOT", "DOGS", "ETHFI", "ENA", "REZ", "BB", "IO", "ZK", "ZRO", "LISTA", "TAO",
    "OM", "ONDO", "AEVO", "ALT", "MANTA", "PYR", "XAI", "AI", "NFP", "GALA", "APE", "GMT",
    "GST", "LDO", "BLUR", "ID", "MAGIC", "HIGH", "GNS", "GMX", "DYDX", "PERP",
    "RDNT", "FXS", "PENDLE", "ETHW", "CFX", "LQTY", "JOE", "T", "MASK", "LRC", "BAL",
    "REN", "KNC", "BAKE", "ALPHA", "BEL", "RLC", "TRB", "OGN", "NKN", "COTI", "AR",
    "ROSE", "JASMY", "API3", "AUCTION", "POWR", "MTL", "ANT", "SUPER", "W",
    "PIXEL", "DYM", "PORTAL", "AXL", "METIS", "AGIX", "FET",
    "RNDR", "VELO", "TWT", "CAKE", "ALPACA", "BURGER", "DODO",
    "LINA", "AKT", "AGLD", "LOOM", "QUICK", "POND", "PROM", "PHB", "TLM",
    "ALICE", "VOXEL", "YGG", "ILV", "PSG", "BAR", "JUV", "ATM", "CITY", "LAZIO",
]))


def load_binance_symbols() -> list[str]:
    """
    لیست نمادهای واقعاً معامله‌پذیر رو از Binance می‌گیره.
    نکته‌ی مهم: قبلاً این تابع همیشه STATIC_SYMBOLS رو هم به نتیجه اضافه می‌کرد،
    حتی وقتی گرفتن لیست زنده موفق بود. این باعث می‌شد نمادهایی که از فیوچرز
    بایننس حذف شدن (مثلاً بعضی فن‌توکن‌های قدیمی) هنوز قابل انتخاب باشن —
    و چون هیچ‌وقت دیتای قیمت براشون نمیومد، سیگنال برای همیشه با قیمت ثابت/نامعتبر
    گیر می‌کرد. الان اگه لیست زنده با موفقیت و به تعداد معقول گرفته بشه، همون
    به‌تنهایی مرجع می‌شه؛ لیست ثابت فقط وقتی استفاده می‌شه که اتصال به Binance
    ناموفق باشه یا نتیجه‌اش مشکوک به ناقص بودن باشه.
    """
    try:
        url = f"{config.BINANCE_REST_BASE}/fapi/v1/exchangeInfo"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = _json.loads(r.read())
        syms = sorted(set(
            s["baseAsset"]
            for s in data.get("symbols", [])
            if s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL"
        ))
        if len(syms) < 50:
            # پاسخ مشکوکه (خیلی کمه) — احتمالاً پاسخ ناقص/خطا بوده، برای اطمینان ترکیب کن
            combined = sorted(set(syms) | set(STATIC_SYMBOLS))
            log.warning(f"⚠️ پاسخ Binance فقط {len(syms)} نماد داشت — با لیست ثابت ترکیب شد ({len(combined)})")
            return combined
        log.info(f"✅ {len(syms)} نماد واقعی از Binance گرفته شد (مرجع اصلی جستجو)")
        return syms
    except Exception as e:
        log.warning(f"⚠️ لیست ثابت ({len(STATIC_SYMBOLS)} نماد) به‌عنوان فالبک استفاده می‌شه: {e}")
        return STATIC_SYMBOLS


async def load_binance_symbols_async() -> list[str]:
    return await asyncio.to_thread(load_binance_symbols)


def fetch_market_price(display_symbol: str):
    """
    قیمت لحظه‌ای رو مستقیم با یه درخواست REST سبک می‌گیره (برای گزینه‌ی «ورود = مارکت»).
    از فید وب‌سوکت استفاده نمی‌کنیم چون ممکنه هنوز subscribe نشده باشه؛ REST سریع‌تر و مطمئن‌تره.
    """
    try:
        url = f"{config.BINANCE_REST_BASE}/fapi/v1/ticker/price?symbol={display_symbol}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = _json.loads(r.read())
        return float(data["price"])
    except Exception as e:
        log.warning(f"⚠️ خطا در گرفتن قیمت مارکت {display_symbol}: {e}")
        return None


async def fetch_market_price_async(display_symbol: str):
    return await asyncio.to_thread(fetch_market_price, display_symbol)


def search_symbols(query: str) -> list[str]:
    q = query.upper().replace("USDT", "").strip()
    if not q:
        return QUICK_SYMBOLS
    prefix = [s for s in ALL_SYMBOLS if s.startswith(q)]
    if len(prefix) >= 20:
        return prefix[:20]
    contains = [s for s in ALL_SYMBOLS if q in s and s not in prefix]
    return (prefix + contains)[:20]

# ─── کمکی‌ها ───────────────────────────────────────────────────────────────


def only_owner(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if uid != config.OWNER_ID:
            if update.callback_query:
                await update.callback_query.answer("⛔️ دسترسی ندارید.", show_alert=True)
            elif update.message:
                await update.message.reply_text("⛔️ فقط مالک ربات می‌تونه دستور بده.")
            return ConversationHandler.END
        return await func(update, context)
    return wrapper


def to_ws_symbol(s: str) -> str:
    s = s.upper().replace("USDT", "").strip("-").strip()
    return f"{s}-SWAP-USDT"


def to_display_symbol(s: str) -> str:
    s = s.upper().replace("USDT", "").strip("-").strip()
    return f"{s}USDT"


def validate_sl_direction(side: str, entry: float, sl: float) -> bool:
    return sl < entry if side == "LONG" else sl > entry


def validate_tp_direction(side: str, entry: float, tp: float) -> bool:
    return tp > entry if side == "LONG" else tp < entry


async def _maybe_unsubscribe(ws_symbol: str):
    still_needed = any(s.status == "OPEN" and s.ws_symbol == ws_symbol for s in signals.values())
    if not still_needed:
        await feed.unsubscribe(ws_symbol)

# ─── داشبورد ────────────────────────────────────────────────────────────────


def format_dashboard_text() -> str:
    """متن داشبورد — لیست فشرده همه‌ی معاملات باز"""
    open_sigs = [s for s in signals.values() if s.status == "OPEN"]
    ts = time.strftime("%H:%M:%S")
    if not open_sigs:
        return (
            f"📊 <b>داشبورد معاملات باز</b>\n{SEP}\n"
            "⚪️ در حال حاضر هیچ معامله‌ی بازی وجود نداره.\n"
            f"\n🕒 {ts}"
        )
    lines = [f"📊 <b>داشبورد معاملات باز</b>  ({len(open_sigs)} معامله)\n{SEP}"]
    for sig in open_sigs:
        price = feed.get_price(sig.ws_symbol)
        pnl = sig.pnl_percent(price) if price else 0.0
        mood = "🟢" if pnl > 0.0001 else ("🔴" if pnl < -0.0001 else "⚪️")
        side_fa = "L" if sig.side == "LONG" else "S"
        sl_txt = f"SL {sig.stop_loss}" if sig.stop_loss else "بدون SL"
        tp_txt = f"TP {sig.take_profit}" if sig.take_profit else "بدون TP"
        price_txt = f"{price:,.4f}".rstrip("0").rstrip(".") if price else "..."
        lines.append(
            f"{mood} <b>{sig.symbol}</b>  [{side_fa} {sig.leverage}x]\n"
            f"    ورود: <code>{sig.entry}</code>  |  لحظه‌ای: <code>{price_txt}</code>  |  <b>{pnl:+.2f}%</b>\n"
            f"    {sl_txt}  •  {tp_txt}\n"
            f"    🆔 <code>{sig.id}</code>"
        )
    lines.append(f"\n{SEP}\n🕒 {ts}")
    return "\n".join(lines)


def make_dashboard_keyboard() -> InlineKeyboardMarkup:
    """
    داشبورد خصوصی — برای هر معامله‌ی باز یه ردیف دکمه داره.
    کانال نسخه‌ی بدون دکمه می‌گیره (چون همه می‌بینن).
    """
    open_sigs = [s for s in signals.values() if s.status == "OPEN"]
    rows = []
    for sig in open_sigs:
        price = feed.get_price(sig.ws_symbol)
        pnl = sig.pnl_percent(price) if price else 0.0
        mood = "🟢" if pnl > 0.0001 else ("🔴" if pnl < -0.0001 else "⚪️")
        # ردیف عنوان: فقط نشانه‌گر — کلیک‌ناپذیر (callback یه space)
        label = f"{mood} {sig.symbol} {sig.side} {pnl:+.2f}%"
        rows.append([InlineKeyboardButton(label, callback_data=f"db_info_{sig.id}")])
        # ردیف دکمه‌های عملیاتی
        rows.append([
            InlineKeyboardButton("🛑 SL", callback_data=f"db_sl_{sig.id}"),
            InlineKeyboardButton("🏁 TP", callback_data=f"db_tp_{sig.id}"),
            InlineKeyboardButton("📊 جزئیات", callback_data=f"db_detail_{sig.id}"),
            InlineKeyboardButton("❌ بستن", callback_data=f"db_close_{sig.id}"),
        ])
    rows.append([InlineKeyboardButton("🔄 رفرش دستی", callback_data="db_refresh")])
    return InlineKeyboardMarkup(rows)


async def _edit_dashboard(bot, chat_id: int, message_id: int, with_keyboard: bool) -> bool:
    """یه نمونه‌ی داشبورد رو ادیت می‌کنه"""
    text = format_dashboard_text()
    kb = make_dashboard_keyboard() if with_keyboard else None
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text=text, parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
        return True
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return True
        log.warning(f"خطای ادیت داشبورد ({chat_id}): {e}")
        return False
    except (RetryAfter, TimedOut):
        return False
    except Exception:
        log.exception(f"خطای غیرمنتظره در ادیت داشبورد ({chat_id})")
        return False


async def refresh_dashboards(bot):
    """هر دو داشبورد (کانال + خصوصی) رو آپدیت می‌کنه — از حلقه‌ی اصلی صدا زده می‌شه"""
    ch = dashboard.get("channel")
    if ch:
        await _edit_dashboard(bot, ch[0], ch[1], with_keyboard=False)
        await asyncio.sleep(config.EDIT_SPACING_SECONDS)

    pr = dashboard.get("private")
    if pr:
        await _edit_dashboard(bot, pr[0], pr[1], with_keyboard=True)


# ─── دستورات داشبورد ────────────────────────────────────────────────────────

@only_owner
async def cmd_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /dashboard — پیام داشبورد رو تو همین چت (خصوصی owner) ایجاد یا پیدا می‌کنه.
    اگه قبلاً ساخته شده بود، فقط آدرسش رو تو حافظه ثبت می‌کنه.
    """
    text = format_dashboard_text()
    kb = make_dashboard_keyboard()
    msg = await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    dashboard["private"] = (msg.chat_id, msg.message_id)
    await update.message.reply_text(
        "✅ داشبورد خصوصی ایجاد شد — از این به بعد خودکار آپدیت می‌شه.\n"
        "برای داشبورد کانال: /dashboardchannel",
    )


@only_owner
async def cmd_dashboard_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /dashboardchannel — داشبورد (بدون دکمه) رو تو کانال پست می‌کنه.
    فقط یه پیام ثابت می‌مونه و زنده آپدیت می‌شه.
    """
    text = format_dashboard_text()
    msg = await context.bot.send_message(chat_id=config.CHANNEL_ID, text=text, parse_mode=ParseMode.HTML)
    dashboard["channel"] = (msg.chat_id, msg.message_id)
    await update.message.reply_text(
        f"✅ داشبورد کانال پست شد — از این به بعد خودکار آپدیت می‌شه.\n"
        f"(message_id: {msg.message_id})"
    )

# ─── Callback‌های داشبورد خصوصی ─────────────────────────────────────────────


async def db_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندلر مرکزی همه‌ی دکمه‌های داشبورد"""
    q = update.callback_query
    uid = update.effective_user.id if update.effective_user else None
    if uid != config.OWNER_ID:
        await q.answer("⛔️ دسترسی ندارید.", show_alert=True)
        return

    data = q.data

    # ─── رفرش دستی ───
    if data == "db_refresh":
        await q.answer("🔄 آپدیت شد")
        await _edit_dashboard(q.bot, q.message.chat_id, q.message.message_id, with_keyboard=True)
        return

    # ─── اطلاعات (کلیک روی ردیف عنوان) ───
    if data.startswith("db_info_"):
        sig_id = data[8:]
        sig = signals.get(sig_id)
        if not sig:
            await q.answer("سیگنال پیدا نشد.", show_alert=True)
            return
        price = feed.get_price(sig.ws_symbol)
        await q.answer(
            f"{sig.symbol} | {sig.side} {sig.leverage}x\n"
            f"ورود: {sig.entry} | لحظه‌ای: {price or '...'}\n"
            f"SL: {sig.stop_loss or '-'} | TP: {sig.take_profit or '-'}",
            show_alert=True,
        )
        return

    # ─── جزئیات کامل ───
    if data.startswith("db_detail_"):
        sig_id = data[10:]
        sig = signals.get(sig_id)
        if not sig:
            await q.answer("سیگنال پیدا نشد.", show_alert=True)
            return
        price = feed.get_price(sig.ws_symbol)
        detail = format_signal_message(sig, price)
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("« برگشت", callback_data="db_refresh")]])
        await q.edit_message_text(detail, parse_mode=ParseMode.HTML, reply_markup=back_kb)
        return

    # ─── بستن معامله ───
    if data.startswith("db_close_"):
        sig_id = data[9:]
        sig = signals.get(sig_id)
        if not sig or sig.status != "OPEN":
            await q.answer("سیگنال پیدا نشد یا از قبل بسته‌ست.", show_alert=True)
            return
        price = feed.get_price(sig.ws_symbol)
        if price is None:
            await q.answer("⚠️ قیمت نامعتبر — از /close id price استفاده کن.", show_alert=True)
            return
        sig.status = "CLOSED"
        sig.closed_price = price
        sig.closed_at = time.time()
        storage.save_signals(signals)
        await update_channel_message(q.bot, sig, price, force=True)
        await _maybe_unsubscribe(sig.ws_symbol)
        await q.answer(f"✅ {sig.symbol} بسته شد.", show_alert=True)
        await _edit_dashboard(q.bot, q.message.chat_id, q.message.message_id, with_keyboard=True)
        return

    # ─── ست SL از داشبورد ───
    if data.startswith("db_sl_"):
        sig_id = data[6:]
        sig = signals.get(sig_id)
        if not sig or sig.status != "OPEN":
            await q.answer("سیگنال پیدا نشد.", show_alert=True)
            return
        context.user_data["db_action"] = "sl"
        context.user_data["db_sig_id"] = sig_id
        context.user_data["db_msg_id"] = q.message.message_id
        context.user_data["db_chat_id"] = q.message.chat_id
        await q.answer()
        await q.message.reply_text(
            f"🛑 <b>ست حد ضرر برای {sig.symbol}</b>\n"
            f"ورود: <code>{sig.entry}</code>  |  جهت: {sig.side}\n\n"
            "قیمت حد ضرر رو تایپ کن:",
            parse_mode=ParseMode.HTML,
        )
        return DB_AWAIT_SL

    # ─── ست TP از داشبورد ───
    if data.startswith("db_tp_"):
        sig_id = data[6:]
        sig = signals.get(sig_id)
        if not sig or sig.status != "OPEN":
            await q.answer("سیگنال پیدا نشد.", show_alert=True)
            return
        context.user_data["db_action"] = "tp"
        context.user_data["db_sig_id"] = sig_id
        context.user_data["db_msg_id"] = q.message.message_id
        context.user_data["db_chat_id"] = q.message.chat_id
        await q.answer()
        await q.message.reply_text(
            f"🏁 <b>ست حد سود برای {sig.symbol}</b>\n"
            f"ورود: <code>{sig.entry}</code>  |  جهت: {sig.side}\n\n"
            "قیمت حد سود رو تایپ کن:",
            parse_mode=ParseMode.HTML,
        )
        return DB_AWAIT_TP


async def db_await_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت قیمت SL یا TP که از داشبورد درخواست شده"""
    if update.effective_user.id != config.OWNER_ID:
        return

    action = context.user_data.get("db_action")
    sig_id = context.user_data.get("db_sig_id")
    db_chat_id = context.user_data.get("db_chat_id")
    db_msg_id = context.user_data.get("db_msg_id")

    if not action or not sig_id:
        return ConversationHandler.END

    try:
        price_val = float(update.message.text.strip().replace(",", ""))
        if price_val <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ قیمت معتبر وارد کن (مثلاً 65000)")
        return DB_AWAIT_SL if action == "sl" else DB_AWAIT_TP

    sig = signals.get(sig_id)
    if not sig:
        await update.message.reply_text("❌ سیگنال دیگه موجود نیست.")
        return ConversationHandler.END

    if action == "sl":
        sig.stop_loss = price_val
        await update.message.reply_text(
            f"✅ حد ضرر <b>{sig.symbol}</b> روی <code>{price_val}</code> تنظیم شد.",
            parse_mode=ParseMode.HTML,
        )
    else:
        sig.take_profit = price_val
        await update.message.reply_text(
            f"✅ حد سود <b>{sig.symbol}</b> روی <code>{price_val}</code> تنظیم شد.",
            parse_mode=ParseMode.HTML,
        )

    storage.save_signals(signals)

    # داشبورد خصوصی رو فوری آپدیت کن
    if db_chat_id and db_msg_id:
        await _edit_dashboard(context.bot, db_chat_id, db_msg_id, with_keyboard=True)

    context.user_data.clear()
    return ConversationHandler.END

# ─── کیبورد همیشگی (پایین چت) ─────────────────────────────────────────────


MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("📊 سیگنال جدید"), KeyboardButton("📋 لیست سیگنال‌ها")],
     [KeyboardButton("🖥 داشبورد"), KeyboardButton("📈 گزارش")]],
    resize_keyboard=True,
    is_persistent=True,
)

# ─── کیبوردهای Inline ───────────────────────────────────────────────────────


def make_symbol_keyboard(results: list[str] = None):
    syms = results if results is not None else QUICK_SYMBOLS
    rows = []
    row = []
    for s in syms:
        row.append(InlineKeyboardButton(f"🪙 {s}", callback_data=f"sym_{s}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🔍  جستجوی نماد دیگه", callback_data="sym_search")])
    rows.append([InlineKeyboardButton("❌  لغو", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)


def make_side_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈  LONG", callback_data="side_LONG"),
         InlineKeyboardButton("📉  SHORT", callback_data="side_SHORT")],
        [InlineKeyboardButton("❌  لغو", callback_data="cancel")],
    ])


def make_leverage_keyboard():
    rows = [[InlineKeyboardButton(f"⚡️ {l}x", callback_data=f"lev_{l}") for l in QUICK_LEVERAGES]]
    rows.append([InlineKeyboardButton("✏️  عدد دیگه‌ای دارم", callback_data="lev_custom")])
    rows.append([InlineKeyboardButton("❌  لغو", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)


def make_entry_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡️  ورود = قیمت مارکت (لحظه‌ای)", callback_data="entry_market")],
        [InlineKeyboardButton("❌  لغو", callback_data="cancel")],
    ])


def make_skip_keyboard(cb: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭  رد کردن", callback_data=cb)],
        [InlineKeyboardButton("❌  لغو", callback_data="cancel")],
    ])


def make_confirm_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅  ثبت و پست در کانال", callback_data="confirm_yes"),
         InlineKeyboardButton("❌  لغو", callback_data="confirm_no")],
    ])


def draft_text(d: dict) -> str:
    side_fa = "لانگ 📈" if d.get("side") == "LONG" else "شورت 📉"
    sl = d.get("stop_loss")
    tp = d.get("take_profit")
    entry_txt = f"مارکت (<code>{d.get('entry', '—')}</code>)" if d.get("entry_is_market") else f"<code>{d.get('entry', '—')}</code>"
    return (
        f"✦ <b>خلاصه سیگنال</b>\n{SEP}\n"
        f"🪙  نماد    »  <code>{d.get('symbol', '—')}</code>\n"
        f"📊  جهت     »  {side_fa}\n"
        f"⚡️  اهرم    »  <code>{d.get('leverage', '—')}x</code>\n"
        f"🎯  ورود    »  {entry_txt}\n"
        f"🛑  حد ضرر  »  <code>{sl if sl else 'ندارد'}</code>\n"
        f"🏁  حد سود  »  <code>{tp if tp else 'ندارد'}</code>\n"
        f"{SEP}"
    )

# ─── شروع سیگنال ───────────────────────────────────────────────────────────


async def _start_signal(message, context):
    context.user_data.clear()
    await message.reply_text(
        f"✦ <b>ثبت سیگنال جدید</b>\n{SEP}\n🪙  <b>نماد ارز رو انتخاب کن:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=make_symbol_keyboard(),
    )
    return SYMBOL_MENU


@only_owner
async def cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _start_signal(update.message, context)


@only_owner
async def btn_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _start_signal(update.message, context)


@only_owner
async def btn_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دکمه «🖥 داشبورد» از کیبورد همیشگی"""
    text = format_dashboard_text()
    kb = make_dashboard_keyboard()
    msg = await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    dashboard["private"] = (msg.chat_id, msg.message_id)

# ─── انتخاب نماد ───────────────────────────────────────────────────────────


@only_owner
async def step_symbol_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        await q.edit_message_text("❌ سیگنال لغو شد.")
        return ConversationHandler.END
    if q.data == "sym_search":
        await q.edit_message_text(
            f"🔍 <b>جستجوی نماد</b>\n{SEP}\n"
            "حروف نماد رو بنویس (هر جای اسم می‌تونه باشه):\n\n"
            "مثلاً  <code>b</code>  →  BTC, BNB, ...\n"
            "مثلاً  <code>pe</code>  →  PEPE, ...",
            parse_mode=ParseMode.HTML,
        )
        return SYMBOL_SEARCH
    sym = q.data.replace("sym_", "")
    return await _set_symbol(q.message, context, sym, edit=True, query=q)


@only_owner
async def step_symbol_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    results = search_symbols(query)
    if not results:
        await update.message.reply_text(f"❌ هیچ نمادی با «{query}» پیدا نشد.\nدوباره امتحان کن:")
        return SYMBOL_SEARCH
    kb = make_symbol_keyboard(results)
    await update.message.reply_text(
        f"🔍 نتایج برای «<code>{query.upper()}</code>» ({len(results)} مورد):",
        parse_mode=ParseMode.HTML, reply_markup=kb,
    )
    return SYMBOL_MENU


async def _set_symbol(message, context, sym: str, edit=False, query=None):
    context.user_data["ws_symbol"] = to_ws_symbol(sym)
    context.user_data["symbol"] = to_display_symbol(sym)
    text = (
        f"✅  نماد: <code>{context.user_data['symbol']}</code>\n\n"
        f"{SEP}\n📊  <b>جهت معامله رو انتخاب کن:</b>"
    )
    if edit and query:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=make_side_keyboard())
    else:
        await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=make_side_keyboard())
    return SIDE

# ─── جهت ───────────────────────────────────────────────────────────────────


@only_owner
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
        f"✅  جهت: {side_fa}\n\n{SEP}\n⚡️  <b>اهرم رو انتخاب کن:</b>",
        parse_mode=ParseMode.HTML, reply_markup=make_leverage_keyboard(),
    )
    return LEVERAGE

# ─── اهرم ───────────────────────────────────────────────────────────────────


@only_owner
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
        f"✅  اهرم: <code>{lev}x</code>\n\n{SEP}\n🎯  <b>نقطه ورود رو تایپ کن</b>، یا از دکمه‌ی زیر برای ورود در قیمت مارکت استفاده کن:\n\nمثلاً: <code>65800</code>",
        parse_mode=ParseMode.HTML, reply_markup=make_entry_keyboard(),
    )
    return ENTRY


@only_owner
async def step_leverage_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        lev = float(update.message.text.strip())
        if lev <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ عدد معتبر وارد کن (مثلاً 15)")
        return LEVERAGE_CUSTOM
    context.user_data["leverage"] = lev
    await update.message.reply_text(
        f"✅  اهرم: <code>{lev}x</code>\n\n{SEP}\n🎯  <b>نقطه ورود رو تایپ کن</b>، یا از دکمه‌ی زیر برای ورود در قیمت مارکت استفاده کن:\n\nمثلاً: <code>65800</code>",
        parse_mode=ParseMode.HTML, reply_markup=make_entry_keyboard(),
    )
    return ENTRY

# ─── ورود ───────────────────────────────────────────────────────────────────


async def _entry_done(message_or_query, context, entry: float, is_market: bool, edit=False):
    context.user_data["entry"] = entry
    context.user_data["entry_is_market"] = is_market
    label = f"مارکت (<code>{entry}</code>)" if is_market else f"<code>{entry}</code>"
    text = (
        f"✅  ورود: {label}\n\n{SEP}\n🛑  <b>حد ضرر رو تایپ کن یا رد کن:</b>"
    )
    kb = make_skip_keyboard("sl_skip")
    if edit:
        await message_or_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await message_or_query.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    return SL


@only_owner
async def step_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        entry = float(update.message.text.strip().replace(",", ""))
        if entry <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ قیمت معتبر وارد کن (مثلاً 65800)", reply_markup=make_entry_keyboard())
        return ENTRY
    return await _entry_done(update.message, context, entry, is_market=False)


@only_owner
async def step_entry_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("⏳ در حال گرفتن قیمت لحظه‌ای...")
    if q.data == "cancel":
        await q.edit_message_text("❌ سیگنال لغو شد.")
        return ConversationHandler.END
    symbol = context.user_data.get("symbol")
    if not symbol:
        await q.edit_message_text("❌ خطای داخلی — دوباره با /signal شروع کن.")
        return ConversationHandler.END
    price = await fetch_market_price_async(symbol)
    if price is None:
        await q.edit_message_text(
            "⚠️ گرفتن قیمت مارکت الان ممکن نشد. لطفاً نقطه ورود رو دستی تایپ کن:",
            reply_markup=make_entry_keyboard(),
        )
        return ENTRY
    return await _entry_done(q, context, price, is_market=True, edit=True)

# ─── حد ضرر ─────────────────────────────────────────────────────────────────


@only_owner
async def step_sl_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sl = float(update.message.text.strip().replace(",", ""))
        if sl <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ قیمت معتبر وارد کن یا دکمه رد کردن رو بزن.")
        return SL
    side = context.user_data["side"]
    entry = context.user_data["entry"]
    if not validate_sl_direction(side, entry, sl):
        direction = "پایین‌تر از" if side == "LONG" else "بالاتر از"
        await update.message.reply_text(
            f"⚠️ برای پوزیشن {side}، حد ضرر باید {direction} نقطه ورود (<code>{entry}</code>) باشه.\n"
            "دوباره وارد کن یا رد کن:",
            parse_mode=ParseMode.HTML, reply_markup=make_skip_keyboard("sl_skip"),
        )
        return SL
    context.user_data["stop_loss"] = sl
    await update.message.reply_text(
        f"✅  حد ضرر: <code>{sl}</code>\n\n{SEP}\n🏁  <b>حد سود رو تایپ کن یا رد کن:</b>",
        parse_mode=ParseMode.HTML, reply_markup=make_skip_keyboard("tp_skip"),
    )
    return TP


@only_owner
async def step_sl_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        await q.edit_message_text("❌ سیگنال لغو شد.")
        return ConversationHandler.END
    context.user_data["stop_loss"] = None
    await q.edit_message_text(
        f"⏭  حد ضرر: ندارد\n\n{SEP}\n🏁  <b>حد سود رو تایپ کن یا رد کن:</b>",
        parse_mode=ParseMode.HTML, reply_markup=make_skip_keyboard("tp_skip"),
    )
    return TP

# ─── حد سود ─────────────────────────────────────────────────────────────────


@only_owner
async def step_tp_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tp = float(update.message.text.strip().replace(",", ""))
        if tp <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ قیمت معتبر وارد کن یا دکمه رد کردن رو بزن.")
        return TP
    side = context.user_data["side"]
    entry = context.user_data["entry"]
    if not validate_tp_direction(side, entry, tp):
        direction = "بالاتر از" if side == "LONG" else "پایین‌تر از"
        await update.message.reply_text(
            f"⚠️ برای پوزیشن {side}، حد سود باید {direction} نقطه ورود (<code>{entry}</code>) باشه.\n"
            "دوباره وارد کن یا رد کن:",
            parse_mode=ParseMode.HTML, reply_markup=make_skip_keyboard("tp_skip"),
        )
        return TP
    context.user_data["take_profit"] = tp
    await update.message.reply_text(
        f"✅  حد سود: <code>{tp}</code>\n\n{draft_text(context.user_data)}\n\n<b>ثبت کنم؟</b>",
        parse_mode=ParseMode.HTML, reply_markup=make_confirm_keyboard(),
    )
    return CONFIRM


@only_owner
async def step_tp_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        await q.edit_message_text("❌ سیگنال لغو شد.")
        return ConversationHandler.END
    context.user_data["take_profit"] = None
    await q.edit_message_text(
        f"⏭  حد سود: ندارد\n\n{draft_text(context.user_data)}\n\n<b>ثبت کنم؟</b>",
        parse_mode=ParseMode.HTML, reply_markup=make_confirm_keyboard(),
    )
    return CONFIRM

# ─── تأیید ───────────────────────────────────────────────────────────────────


@only_owner
async def step_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "confirm_no":
        await q.edit_message_text("❌ سیگنال لغو شد.")
        return ConversationHandler.END

    d = context.user_data
    base = d["symbol"].replace("USDT", "").lower()
    sig_id = f"{base}-{uuid.uuid4().hex[:5]}"

    sig = Signal(
        id=sig_id, symbol=d["symbol"], ws_symbol=d["ws_symbol"],
        side=d["side"], leverage=d["leverage"], entry=d["entry"],
        entry_is_market=bool(d.get("entry_is_market", False)),
        stop_loss=d.get("stop_loss"), take_profit=d.get("take_profit"),
        chat_id=config.CHANNEL_ID,
    )

    await feed.subscribe(sig.ws_symbol)
    text = format_signal_message(sig, price=sig.entry)
    msg = await context.bot.send_message(chat_id=config.CHANNEL_ID, text=text, parse_mode=ParseMode.HTML)
    sig.message_id = msg.message_id
    sig.last_sent_text = text
    sig.last_price_used = sig.entry
    signals[sig_id] = sig
    storage.save_signals(signals)

    # داشبورد رو فوری آپدیت کن تا معامله‌ی جدید ظاهر بشه
    await refresh_dashboards(context.bot)

    await q.edit_message_text(
        f"✅  سیگنال ثبت شد و در کانال پست شد!\n{SEP}\n"
        f"🆔  شناسه: <code>{sig_id}</code>\n\n"
        f"برای تنظیم حد ضرر/سود:\n"
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
        sig.stop_loss = float(args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("قیمت نامعتبره.")
        return
    storage.save_signals(signals)
    await update.message.reply_text(
        f"✅ حد ضرر <code>{sig.id}</code> روی <code>{sig.stop_loss}</code> تنظیم شد.",
        parse_mode=ParseMode.HTML,
    )


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
        sig.take_profit = float(args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("قیمت نامعتبره.")
        return
    storage.save_signals(signals)
    await update.message.reply_text(
        f"✅ حد سود <code>{sig.id}</code> روی <code>{sig.take_profit}</code> تنظیم شد.",
        parse_mode=ParseMode.HTML,
    )


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
    if len(args) > 1:
        price = float(args[1].replace(",", ""))
    else:
        price = feed.get_price(sig.ws_symbol)
        if price is None:
            await update.message.reply_text(
                "⚠️ قیمت لحظه‌ای در دسترس نیست. قیمت رو دستی بده:\n"
                f"<code>/close {sig.id} قیمت</code>", parse_mode=ParseMode.HTML,
            )
            return
    sig.status = "CLOSED"
    sig.closed_price = price
    sig.closed_at = time.time()
    storage.save_signals(signals)
    await update_channel_message(context, sig, price, force=True)
    await _maybe_unsubscribe(sig.ws_symbol)
    await refresh_dashboards(context.bot)
    await update.message.reply_text(f"⏹ سیگنال <code>{sig.id}</code> بسته شد.", parse_mode=ParseMode.HTML)


@only_owner
async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("فرمت: /delete <id>")
        return
    sig = signals.pop(args[0], None)
    if not sig:
        await update.message.reply_text("❌ سیگنالی با این شناسه پیدا نشد.")
        return
    storage.save_signals(signals)
    await _maybe_unsubscribe(sig.ws_symbol)
    await refresh_dashboards(context.bot)
    await update.message.reply_text(f"🗑 سیگنال <code>{sig.id}</code> حذف شد.", parse_mode=ParseMode.HTML)


@only_owner
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    open_sigs = [s for s in signals.values() if s.status == "OPEN"]
    if not open_sigs:
        await update.message.reply_text("سیگنال باز فعالی وجود نداره.")
        return
    lines = [f"✦ <b>سیگنال‌های باز</b>\n{SEP}"]
    for s in open_sigs:
        price = feed.get_price(s.ws_symbol)
        pnl = s.pnl_percent(price) if price else 0.0
        mood = "🟢" if pnl > 0 else ("🔴" if pnl < 0 else "⚪️")
        stale = " ⚠️ (قیمت نامعتبر)" if price is None else ""
        lines.append(f"{mood}  <code>{s.id}</code>\n    {s.symbol}  {s.side}  {s.leverage}x  →  {pnl:+.2f}%{stale}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ─── گزارش‌ها ───────────────────────────────────────────────────────────────

REPORT_PERIODS = {"today": "امروز", "week": "۷ روز اخیر", "month": "۳۰ روز اخیر"}


def _closed_signals_in_period(period: str) -> list:
    now = time.time()
    if period == "today":
        lt = time.localtime(now)
        cutoff = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    elif period == "week":
        cutoff = now - 7 * 24 * 3600
    elif period == "month":
        cutoff = now - 30 * 24 * 3600
    else:
        cutoff = 0
    return sorted(
        (s for s in signals.values() if s.status != "OPEN" and s.closed_at and s.closed_at >= cutoff),
        key=lambda s: s.closed_at,
    )


def format_report(period: str, detailed: bool) -> str:
    label = REPORT_PERIODS.get(period, period)
    trades = _closed_signals_in_period(period)
    if not trades:
        return f"📈 <b>گزارش {label}</b>\n{SEP}\nهیچ معامله‌ی بسته‌شده‌ای تو این بازه ثبت نشده."

    pnls = [(s, s.pnl_percent(s.closed_price)) for s in trades]
    wins = [p for _, p in pnls if p > 0]
    losses = [p for _, p in pnls if p < 0]
    total_pnl = sum(p for _, p in pnls)
    avg_pnl = total_pnl / len(pnls)
    win_rate = (len(wins) / len(trades)) * 100
    best_sig, best_pnl = max(pnls, key=lambda t: t[1])
    worst_sig, worst_pnl = min(pnls, key=lambda t: t[1])

    lines = [
        f"📈 <b>گزارش {label}</b>\n{SEP}",
        f"🔢 تعداد معاملات بسته‌شده: <b>{len(trades)}</b>",
        f"🟢 سودده: {len(wins)}  |  🔴 زیان‌ده: {len(losses)}  |  نرخ برد: <b>{win_rate:.1f}%</b>",
        f"📊 مجموع سود/ضرر: <b>{total_pnl:+.2f}%</b>",
        f"📉 میانگین هر معامله: <b>{avg_pnl:+.2f}%</b>",
        f"🏆 بهترین معامله: {best_sig.symbol} ({best_pnl:+.2f}%)",
        f"💀 بدترین معامله: {worst_sig.symbol} ({worst_pnl:+.2f}%)",
    ]

    if detailed:
        lines.append(f"\n{SEP}\n<b>جزئیات معاملات:</b>")
        for s, p in pnls:
            mood = "🟢" if p >= 0 else "🔴"
            closed_ts = time.strftime("%m/%d %H:%M", time.localtime(s.closed_at))
            lines.append(
                f"{mood} <b>{s.symbol}</b> {s.side} {s.leverage}x  |  <b>{p:+.2f}%</b>  |  {closed_ts}  |  <code>{s.id}</code>"
            )

    return "\n".join(lines)


def make_report_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key, label in REPORT_PERIODS.items():
        rows.append([
            InlineKeyboardButton(f"📅 {label} — خلاصه", callback_data=f"rep_{key}_sum"),
            InlineKeyboardButton(f"📋 {label} — با جزئیات", callback_data=f"rep_{key}_det"),
        ])
    return InlineKeyboardMarkup(rows)


@only_owner
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📈 <b>گزارش معاملات</b>\n{SEP}\nبازه‌ی زمانی و نوع گزارش رو انتخاب کن:",
        parse_mode=ParseMode.HTML, reply_markup=make_report_keyboard(),
    )


async def report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id if update.effective_user else None
    if uid != config.OWNER_ID:
        await q.answer("⛔️ دسترسی ندارید.", show_alert=True)
        return
    await q.answer()
    _, period, mode = q.data.split("_")
    detailed = mode == "det"
    text = format_report(period, detailed)
    await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=make_report_keyboard())


@only_owner
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✦ <b>راهنمای دستورات</b>\n"
        f"{SEP}\n"
        "/signal — ثبت سیگنال جدید\n"
        "/list — لیست سیگنال‌های باز\n"
        "/dashboard — داشبورد زنده (چت خصوصی)\n"
        "/dashboardchannel — داشبورد زنده (کانال)\n"
        "/report — گزارش معاملات (امروز/هفته/ماه، خلاصه یا با جزئیات)\n"
        "/setsl id قیمت — تنظیم حد ضرر\n"
        "/settp id قیمت — تنظیم حد سود\n"
        "/close id [قیمت] — بستن دستی سیگنال\n"
        "/delete id — حذف کامل رکورد سیگنال\n"
        "/cancel — لغو مراحل جاری",
        parse_mode=ParseMode.HTML,
    )

# ─── آپدیت زنده ─────────────────────────────────────────────────────────────


async def update_channel_message(ctx, sig: Signal, price, force: bool = False, stale: bool = False) -> bool:
    draft = format_signal_message(sig, price, stale=stale)
    if not force and draft == sig.last_sent_text:
        sig.last_price_used = price
        return False

    sig.updated_at = time.time()
    text = format_signal_message(sig, price, stale=stale)
    bot = ctx.bot if hasattr(ctx, "bot") else ctx
    try:
        await bot.edit_message_text(
            chat_id=sig.chat_id, message_id=sig.message_id,
            text=text, parse_mode=ParseMode.HTML,
        )
        sig.last_sent_text = text
        sig.last_price_used = price
        return True
    except RetryAfter as e:
        log.warning(f"RetryAfter برای {sig.id}: {e.retry_after:.1f}s")
        await asyncio.sleep(e.retry_after)
        return False
    except BadRequest as e:
        if "not modified" in str(e).lower():
            sig.last_sent_text = text
            sig.last_price_used = price
        else:
            log.warning(f"خطای ادیت {sig.id}: {e}")
        return False
    except TimedOut:
        return False
    except Exception:
        log.exception(f"خطای غیرمنتظره در ادیت پیام سیگنال {sig.id}")
        return False


def _should_push(sig: Signal, price: float) -> bool:
    if config.MIN_PRICE_CHANGE_PERCENT <= 0:
        return True
    if sig.last_price_used is None:
        return True
    prev_pnl = sig.pnl_percent(sig.last_price_used)
    new_pnl = sig.pnl_percent(price)
    return abs(new_pnl - prev_pnl) >= config.MIN_PRICE_CHANGE_PERCENT


stale_warned: set[str] = set()  # شناسه‌ی سیگنال‌هایی که قبلاً هشدار قیمت stale براشون رفته


async def price_update_loop(app: Application):
    tick = 0
    while True:
        try:
            any_sent = False
            for sig in list(signals.values()):
                if sig.status != "OPEN":
                    continue
                price = feed.get_price(sig.ws_symbol)
                if price is None:
                    # قیمت نامعتبر/قدیمیه — به‌جای اینکه ساکت برای همیشه فریز بمونه،
                    # یه‌بار به مالک هشدار می‌دیم و پیام کانال رو با نشانه‌ی هشدار به‌روز می‌کنیم
                    if feed.is_stale(sig.ws_symbol) and sig.id not in stale_warned:
                        stale_warned.add(sig.id)
                        last_known = sig.last_price_used
                        try:
                            await app.bot.send_message(
                                chat_id=config.OWNER_ID,
                                text=(
                                    f"⚠️ <b>هشدار قیمت</b>\n"
                                    f"قیمت لحظه‌ای <b>{sig.symbol}</b> (<code>{sig.id}</code>) بیش از "
                                    f"{toobit_feed.STALE_AFTER_SECONDS} ثانیه‌ست از منبع دریافت نمی‌شه.\n"
                                    "احتمال داره این نماد از فیوچرز بایننس حذف/دیلیست شده باشه یا اتصال قطع باشه.\n"
                                    f"آخرین قیمت شناخته‌شده: <code>{last_known if last_known else '—'}</code>"
                                ),
                                parse_mode=ParseMode.HTML,
                            )
                        except Exception:
                            log.exception("خطا در ارسال هشدار قیمت stale")
                        if last_known is not None:
                            await update_channel_message(app, sig, last_known, force=True, stale=True)
                    continue
                else:
                    stale_warned.discard(sig.id)

                sig.record_price(price)

                hit = sig.check_sl_tp(price)
                if hit:
                    sig.status = hit
                    sig.closed_price = price
                    sig.closed_at = time.time()
                    storage.save_signals(signals)
                    await update_channel_message(app, sig, price, force=True)
                    await _maybe_unsubscribe(sig.ws_symbol)
                    continue

                if _should_push(sig, price):
                    sent = await update_channel_message(app, sig, price)
                    if sent:
                        any_sent = True
                        await asyncio.sleep(config.EDIT_SPACING_SECONDS)

            # داشبورد هر ۵ تیک آپدیت می‌شه (به‌طور پیش‌فرض هر ~۶ ثانیه)
            # این رو جدا از آپدیت سیگنال‌ها نگه می‌داریم تا rate limit رو بهینه مصرف کنیم
            tick += 1
            if tick >= 5:
                tick = 0
                await refresh_dashboards(app.bot)

        except Exception:
            log.exception("خطا در حلقه آپدیت قیمت")
        await asyncio.sleep(config.UPDATE_INTERVAL_SECONDS)


async def symbol_refresh_loop():
    global ALL_SYMBOLS
    while True:
        await asyncio.sleep(config.SYMBOL_REFRESH_INTERVAL_SECONDS)
        try:
            ALL_SYMBOLS = await load_binance_symbols_async()
        except Exception:
            log.exception("خطا در تازه‌سازی لیست نمادها")


async def post_init(app: Application):
    global signals, ALL_SYMBOLS
    ALL_SYMBOLS = await load_binance_symbols_async()
    signals = storage.load_signals()
    for sig in signals.values():
        if sig.status == "OPEN":
            await feed.subscribe(sig.ws_symbol)
    asyncio.create_task(feed.run())
    asyncio.create_task(price_update_loop(app))
    asyncio.create_task(symbol_refresh_loop())
    log.info("ربات آماده شد ✅")


async def post_shutdown(app: Application):
    feed.stop()

# ─── main ────────────────────────────────────────────────────────────────────


def main():
    problems = config.validate()
    if problems:
        raise SystemExit("لطفا config.py (یا متغیرهای محیطی) رو کامل کن:\n- " + "\n- ".join(problems))

    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # ConversationHandler برای ثبت سیگنال جدید
    signal_conv = ConversationHandler(
        entry_points=[
            CommandHandler("signal", cmd_signal),
            MessageHandler(filters.Regex("^📊 سیگنال جدید$"), btn_signal),
        ],
        states={
            SYMBOL_MENU:     [CallbackQueryHandler(step_symbol_btn, pattern="^(sym_|cancel)")],
            SYMBOL_SEARCH:   [MessageHandler(filters.TEXT & ~filters.COMMAND, step_symbol_search)],
            SIDE:            [CallbackQueryHandler(step_side, pattern="^(side_|cancel)")],
            LEVERAGE:        [CallbackQueryHandler(step_leverage_btn, pattern="^(lev_|cancel)")],
            LEVERAGE_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_leverage_custom)],
            ENTRY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_entry),
                CallbackQueryHandler(step_entry_market, pattern="^(entry_market|cancel)$"),
            ],
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

    # ConversationHandler برای ست SL/TP از داشبورد
    db_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(db_callback, pattern="^db_(sl|tp)_"),
        ],
        states={
            DB_AWAIT_SL: [MessageHandler(filters.TEXT & ~filters.COMMAND, db_await_price)],
            DB_AWAIT_TP: [MessageHandler(filters.TEXT & ~filters.COMMAND, db_await_price)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True,
    )

    app.add_handler(signal_conv)
    app.add_handler(db_conv)

    # بقیه‌ی callback‌های داشبورد (که نیازی به conversation ندارن)
    app.add_handler(CallbackQueryHandler(db_callback, pattern="^db_(refresh|info_|detail_|close_)"))

    app.add_handler(CommandHandler("dashboard", cmd_dashboard))
    app.add_handler(CommandHandler("dashboardchannel", cmd_dashboard_channel))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CallbackQueryHandler(report_callback, pattern="^rep_"))
    app.add_handler(CommandHandler("setsl", cmd_setsl))
    app.add_handler(CommandHandler("settp", cmd_settp))
    app.add_handler(CommandHandler("close", cmd_close))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.Regex("^📋 لیست سیگنال‌ها$"), cmd_list))
    app.add_handler(MessageHandler(filters.Regex("^🖥 داشبورد$"), btn_dashboard))
    app.add_handler(MessageHandler(filters.Regex("^📈 گزارش$"), cmd_report))

    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != config.OWNER_ID:
            return
        await update.message.reply_text(
            "✅ ربات آماده‌ست!\nاز دکمه‌های پایین استفاده کن، یا /help رو بزن.",
            reply_markup=MAIN_KEYBOARD,
        )
    app.add_handler(CommandHandler("start", cmd_start))

    log.info("ربات در حال اجراست...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
