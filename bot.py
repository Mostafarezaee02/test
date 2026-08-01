"""
ربات سیگنال‌دهی زنده — رابط کاربری کامل دکمه‌ای + جستجوی نماد
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
from signal_model import Signal, format_signal_message
from toobit_feed import ToobitPriceFeed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("bot")

# مراحل
SYMBOL_MENU, SYMBOL_SEARCH, SIDE, LEVERAGE, LEVERAGE_CUSTOM, ENTRY, SL, TP, CONFIRM = range(9)

signals: dict[str, Signal] = {}
feed = ToobitPriceFeed()
ALL_SYMBOLS: list[str] = []   # لیست همه نمادهای فیوچرز Binance

QUICK_SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "XRP", "SUI", "1000SHIB"]
QUICK_LEVERAGES = [5, 10, 20, 25, 50]
SEP = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

# لیست ثابت پشتیبان — همیشه در دسترسه حتی اگه اتصال به Binance REST قطع باشه
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
    """تلاش می‌کنه لیست کامل و به‌روز رو از Binance بگیره، اگه نشد از لیست ثابت استفاده می‌کنه.
    (تابع sync — همیشه از داخل asyncio.to_thread صدا زده می‌شه تا event loop رو بلاک نکنه)"""
    try:
        url = f"{config.BINANCE_REST_BASE}/fapi/v1/exchangeInfo"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = _json.loads(r.read())
        syms = [
            s["baseAsset"]
            for s in data.get("symbols", [])
            if s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL"
        ]
        combined = sorted(set(syms) | set(STATIC_SYMBOLS))
        log.info(f"✅ {len(syms)} نماد از Binance گرفته شد (مجموع با لیست ثابت: {len(combined)})")
        return combined
    except Exception as e:
        log.warning(f"⚠️ نشد نمادهای Binance رو بگیریم، از لیست ثابت ({len(STATIC_SYMBOLS)} نماد) استفاده می‌شه: {e}")
        return STATIC_SYMBOLS


async def load_binance_symbols_async() -> list[str]:
    return await asyncio.to_thread(load_binance_symbols)


def search_symbols(query: str) -> list[str]:
    """جستجوی نماد — اول تطبیق‌های ابتدایی (prefix) بعد تطبیق‌های داخل رشته (contains)"""
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
    """فقط موقع ثبت اولیه‌ی سیگنال چک می‌شه — جلوی اشتباه رایج (جهت غلط) رو می‌گیره.
    برای /setsl بعدی عمداً این چک اعمال نمی‌شه چون trailing-stop (بردن حد ضرر رو به
    سمت سود) کاملاً معتبره."""
    if side == "LONG":
        return sl < entry
    return sl > entry


def validate_tp_direction(side: str, entry: float, tp: float) -> bool:
    if side == "LONG":
        return tp > entry
    return tp < entry


async def _maybe_unsubscribe(ws_symbol: str):
    """اگه دیگه هیچ سیگنال بازی از این نماد استفاده نمی‌کنه، اشتراک وب‌سوکتش رو قطع کن"""
    still_needed = any(s.status == "OPEN" and s.ws_symbol == ws_symbol for s in signals.values())
    if not still_needed:
        await feed.unsubscribe(ws_symbol)

# ─── کیبورد همیشگی (پایین چت) ─────────────────────────────────────────────

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("📊 سیگنال جدید"), KeyboardButton("📋 لیست سیگنال‌ها")]],
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
    return (
        f"✦ <b>خلاصه سیگنال</b>\n{SEP}\n"
        f"🪙  نماد    »  <code>{d.get('symbol', '—')}</code>\n"
        f"📊  جهت     »  {side_fa}\n"
        f"⚡️  اهرم    »  <code>{d.get('leverage', '—')}x</code>\n"
        f"🎯  ورود    »  <code>{d.get('entry', '—')}</code>\n"
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
    """دکمه همیشگی پایین چت"""
    return await _start_signal(update.message, context)

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
    """کاربر حروف تایپ کرد، فیلتر کن و دکمه نشون بده"""
    query = update.message.text.strip()
    results = search_symbols(query)
    if not results:
        await update.message.reply_text(
            f"❌ هیچ نمادی با «{query}» پیدا نشد.\nدوباره امتحان کن:",
        )
        return SYMBOL_SEARCH

    kb = make_symbol_keyboard(results)
    await update.message.reply_text(
        f"🔍 نتایج برای «<code>{query.upper()}</code>» ({len(results)} مورد):",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    return SYMBOL_MENU   # برمیگرده به انتخاب دکمه


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
        f"✅  اهرم: <code>{lev}x</code>\n\n{SEP}\n🎯  <b>نقطه ورود رو تایپ کن:</b>\n\nمثلاً: <code>65800</code>",
        parse_mode=ParseMode.HTML,
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
        f"✅  اهرم: <code>{lev}x</code>\n\n{SEP}\n🎯  <b>نقطه ورود رو تایپ کن:</b>\n\nمثلاً: <code>65800</code>",
        parse_mode=ParseMode.HTML,
    )
    return ENTRY

# ─── ورود ───────────────────────────────────────────────────────────────────


@only_owner
async def step_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        entry = float(update.message.text.strip().replace(",", ""))
        if entry <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ قیمت معتبر وارد کن (مثلاً 65800)")
        return ENTRY
    context.user_data["entry"] = entry
    await update.message.reply_text(
        f"✅  ورود: <code>{entry}</code>\n\n{SEP}\n🛑  <b>حد ضرر رو تایپ کن یا رد کن:</b>",
        parse_mode=ParseMode.HTML, reply_markup=make_skip_keyboard("sl_skip"),
    )
    return SL

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

    await q.edit_message_text(
        f"✅  سیگنال ثبت شد و در کانال پست شد!\n{SEP}\n"
        f"🆔  شناسه: <code>{sig_id}</code>\n\n"
        f"برای تنظیم حد ضرر/سود بعدی:\n"
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
        sig.take_profit = float(args[1].replace(",", ""))
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

    if len(args) > 1:
        price = float(args[1].replace(",", ""))
    else:
        price = feed.get_price(sig.ws_symbol)
        if price is None:
            await update.message.reply_text(
                "⚠️ قیمت لحظه‌ای در دسترس نیست (نامعتبر/قدیمیه). قیمت رو دستی بده:\n"
                f"<code>/close {sig.id} قیمت</code>", parse_mode=ParseMode.HTML,
            )
            return

    sig.status = "CLOSED"
    sig.closed_price = price
    sig.closed_at = time.time()
    storage.save_signals(signals)
    await update_channel_message(context, sig, price, force=True)
    await _maybe_unsubscribe(sig.ws_symbol)
    await update.message.reply_text(f"⏹ سیگنال <code>{sig.id}</code> بسته شد.", parse_mode=ParseMode.HTML)


@only_owner
async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف کامل رکورد سیگنال (بدون ادیت پیام کانال) — برای پاک کردن ورودی اشتباهی"""
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
    await update.message.reply_text(f"🗑 سیگنال <code>{sig.id}</code> کامل حذف شد.", parse_mode=ParseMode.HTML)


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


@only_owner
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✦ <b>راهنمای دستورات</b>\n"
        f"{SEP}\n"
        "/signal — ثبت سیگنال جدید (یا دکمه «📊 سیگنال جدید»)\n"
        "/list — لیست سیگنال‌های باز\n"
        "/setsl id قیمت — تنظیم/تغییر حد ضرر\n"
        "/settp id قیمت — تنظیم/تغییر حد سود\n"
        "/close id [قیمت] — بستن دستی سیگنال\n"
        "/delete id — حذف کامل رکورد سیگنال\n"
        "/cancel — لغو مراحل ثبت سیگنال جاری",
        parse_mode=ParseMode.HTML,
    )

# ─── آپدیت زنده ─────────────────────────────────────────────────────────────


async def update_channel_message(ctx, sig: Signal, price, force: bool = False) -> bool:
    """
    پیام کانال رو در صورت نیاز ادیت می‌کنه.
    نکته‌ی مهم: متن پیشنهادی رو با updated_at *فعلی* (قدیمی) می‌سازیم و با
    last_sent_text مقایسه می‌کنیم — نه با یه تایم‌استمپ تازه. اگه قیمت واقعاً عوض
    نشده باشه این دو متن کاملاً یکی درمیان و ادیت الکی فرستاده نمی‌شه. فقط وقتی
    واقعاً چیزی فرق کرده، updated_at رو تازه می‌کنیم و پیام رو با تایم‌استمپ جدید می‌فرستیم.
    """
    draft = format_signal_message(sig, price)
    if not force and draft == sig.last_sent_text:
        sig.last_price_used = price
        return False

    sig.updated_at = time.time()
    text = format_signal_message(sig, price)

    bot = ctx.bot if hasattr(ctx, "bot") else ctx
    try:
        await bot.edit_message_text(chat_id=sig.chat_id, message_id=sig.message_id, text=text, parse_mode=ParseMode.HTML)
        sig.last_sent_text = text
        sig.last_price_used = price
        return True
    except RetryAfter as e:
        log.warning(f"RetryAfter برای {sig.id}: {e.retry_after:.1f}s صبر می‌کنیم")
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
    """فیلتر اولیه و سریع قبل از ساختن متن کامل — از حرکت‌های ریز صرف‌نظر می‌کنه"""
    if config.MIN_PRICE_CHANGE_PERCENT <= 0:
        return True
    if sig.last_price_used is None:
        return True
    prev_pnl = sig.pnl_percent(sig.last_price_used)
    new_pnl = sig.pnl_percent(price)
    return abs(new_pnl - prev_pnl) >= config.MIN_PRICE_CHANGE_PERCENT


async def price_update_loop(app: Application):
    while True:
        try:
            for sig in list(signals.values()):
                if sig.status != "OPEN":
                    continue
                price = feed.get_price(sig.ws_symbol)
                if price is None:
                    continue

                sig.record_price(price)  # آمار بیشترین سود/افت مستقل از ارسال پیام

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
                        # فاصله‌ی کوتاه بین ادیت‌های پشت‌سرهم به یک چت تا burst باعث فلود-کنترل نشه
                        await asyncio.sleep(config.EDIT_SPACING_SECONDS)
        except Exception:
            log.exception("خطا در حلقه آپدیت قیمت")
        await asyncio.sleep(config.UPDATE_INTERVAL_SECONDS)


async def symbol_refresh_loop():
    """لیست نمادها رو دوره‌ای تازه می‌کنه تا نمادهای جدید لیست‌شده هم تو جستجو باشن"""
    global ALL_SYMBOLS
    while True:
        await asyncio.sleep(config.SYMBOL_REFRESH_INTERVAL_SECONDS)
        try:
            ALL_SYMBOLS = await load_binance_symbols_async()
        except Exception:
            log.exception("خطا در تازه‌سازی لیست نمادها")


async def post_init(app: Application):
    global signals, ALL_SYMBOLS
    ALL_SYMBOLS = await load_binance_symbols_async()   # بدون بلاک کردن event loop
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

    conv = ConversationHandler(
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
    app.add_handler(CommandHandler("setsl", cmd_setsl))
    app.add_handler(CommandHandler("settp", cmd_settp))
    app.add_handler(CommandHandler("close", cmd_close))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("help", cmd_help))
    # دکمه لیست از کیبورد همیشگی
    app.add_handler(MessageHandler(filters.Regex("^📋 لیست سیگنال‌ها$"), cmd_list))

    # ارسال کیبورد همیشگی به owner بعد از /start
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
