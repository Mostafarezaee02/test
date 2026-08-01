"""
تنظیمات ربات - قبل از اجرا این مقادیر رو پر کن (یا به صورت متغیر محیطی بده)
"""

import os

# توکن ربات تلگرام (از BotFather)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")

# آیدی عددی کانال (باید ربات ادمین کانال باشه)
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-1000000000000"))

# آیدی عددی خودت در تلگرام (فقط تو اجازه داری به ربات دستور بدی)
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

# هر چند ثانیه یک‌بار قیمت چک بشه و در صورت نیاز پیام کانال ادیت بشه.
# تلگرام برای ادیت مکرر یک پیام محدودیت نرخ داره؛ زیر ~۱ ثانیه عملاً با خطای
# RetryAfter مواجه می‌شی — این محدودیت رو خود تلگرام تحمیل می‌کنه، نه کد.
UPDATE_INTERVAL_SECONDS = float(os.environ.get("UPDATE_INTERVAL_SECONDS", "1.2"))

# حداقل تغییر PnL٪ که باعث ادیت واقعی پیام می‌شه (جلوگیری از ادیت الکی وقتی قیمت
# عملاً ثابته). هر چقدر این عدد رو بالاتر ببری، ادیت‌های کمتری می‌ره و فاصله‌ی
# UPDATE_INTERVAL_SECONDS رو می‌تونی امن‌تر پایین بیاری، چون فقط حرکت‌های واقعی
# باعث ادیت می‌شن نه هر تیک. صفر یعنی رفتار قدیمی: هر تیک ادیت کن.
MIN_PRICE_CHANGE_PERCENT = float(os.environ.get("MIN_PRICE_CHANGE_PERCENT", "0.02"))

# حداقل فاصله بین چند ادیت پشت‌سرهم وقتی چند سیگنال هم‌زمان باز داری — برای
# جلوگیری از burst که خودش (حتی با میانگین نرخ درست) باعث فلود-کنترل تلگرام می‌شه.
EDIT_SPACING_SECONDS = float(os.environ.get("EDIT_SPACING_SECONDS", "0.35"))

# هر چند وقت یک‌بار لیست نمادهای فیوچرز Binance دوباره تازه بشه (پوشش نمادهای تازه لیست‌شده)
SYMBOL_REFRESH_INTERVAL_SECONDS = int(os.environ.get("SYMBOL_REFRESH_INTERVAL_SECONDS", str(6 * 3600)))

BINANCE_REST_BASE = "https://fapi.binance.com"
BINANCE_WS_URL = "wss://fstream.binance.com/stream"

# فایل ذخیره سیگنال‌های فعال (برای اینکه با ری‌استارت ربات سیگنال‌ها از دست نرن)
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


def validate() -> list[str]:
    """قبل از اجرا چک می‌کنه که مقادیر ضروری واقعاً پر شده باشن"""
    problems = []
    if not BOT_TOKEN or BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        problems.append("BOT_TOKEN تنظیم نشده")
    if CHANNEL_ID == -1000000000000:
        problems.append("CHANNEL_ID تنظیم نشده")
    if OWNER_ID == 0:
        problems.append("OWNER_ID تنظیم نشده")
    return problems
