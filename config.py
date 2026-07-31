"""
تنظیمات ربات - قبل از اجرا این مقادیر رو پر کن
"""

import os

# توکن ربات تلگرام (از BotFather)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")

# آیدی عددی کانال (باید ربات ادمین کانال باشه)
# مثال: -1001234567890
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-1000000000000"))

# آیدی عددی خودت در تلگرام (فقط تو اجازه داری به ربات دستور بدی)
# با ربات @userinfobot میتونی آیدیتو بگیری
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

# هر چند ثانیه یک‌بار پیام کانال ادیت بشه.
# تلگرام محدودیت نرخ ادیت داره، زیر ۱ ثانیه عملا با ارور RetryAfter مواجه میشی.
UPDATE_INTERVAL_SECONDS = float(os.environ.get("UPDATE_INTERVAL_SECONDS", "1.5"))

# حداقل تغییر قیمت (به درصد) که باعث ادیت پیام بشه، برای جلوگیری از ادیت‌های الکی
MIN_PRICE_CHANGE_PERCENT = float(os.environ.get("MIN_PRICE_CHANGE_PERCENT", "0.0"))

# آدرس وب‌سوکت توبیت (فیوچرز/پرپچوال)
TOOBIT_WS_URL = "wss://stream.toobit.com/quote/ws/v1"

# فایل ذخیره سیگنال‌های فعال (برای اینکه با ری‌استارت ربات سیگنال‌ها از دست نرن)
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")
