# ربات سیگنال زنده تلگرام (توبیت)

این ربات وقتی بهش سیگنال میدی (مثلا `ETH LONG 10 1800`)، پیام رو با فرمت شیک تو کانالت پست می‌کنه
و بعد به صورت مداوم قیمت لحظه‌ای رو از توبیت می‌گیره، درصد سود/ضرر (با احتساب اهرم) رو حساب می‌کنه
و همون پیام رو ادیت می‌کنه. رنگ (🟢/🔴) و ایموجی‌ها بر اساس سود یا ضرر بودن عوض می‌شن.

## ⚠️ محدودیت واقعی سرعت
تلگرام برای ادیت مکرر یک پیام محدودیت نرخ داره. اگه بخوای هر کمتر از ۱ ثانیه ادیت کنی،
تلگرام خودش با خطای `Flood control / RetryAfter` جلوتو می‌گیره. مقدار پیش‌فرض این ربات
هر **۱.۵ ثانیه** یک بار ادیت می‌کنه که هم امن هست و هم از نظر چشم کاملا «زنده» دیده میشه.
این عدد رو می‌تونی تو `config.py` (متغیر `UPDATE_INTERVAL_SECONDS`) کم و زیاد کنی، ولی
پایین‌تر از ~۱ ثانیه ریسک بلاک موقت شدن ربات رو داره.

## نصب

```bash
cd toobit_signal_bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## تنظیمات

فایل `config.py` رو باز کن و این‌ها رو پر کن:

- `BOT_TOKEN`: توکن ربات (از @BotFather)
- `CHANNEL_ID`: آیدی عددی کانالت (باید ربات رو به عنوان ادمین با دسترسی پست/ادیت پیام به کانال اضافه کنی).
  برای گرفتن آیدی کانال، یک پیام تو کانال فوروارد کن به ربات @userinfobot یا @getidsbot
- `OWNER_ID`: آیدی عددی خودت (برای اینکه فقط تو بتونی به ربات دستور بدی)

می‌تونی این مقادیر رو به جای ادیت فایل، به صورت متغیر محیطی هم بدی:

```bash
export BOT_TOKEN="123456:AA...."
export CHANNEL_ID="-1001234567890"
export OWNER_ID="123456789"
```

## اجرا

```bash
python3 bot.py
```

## دستورات (فقط برای OWNER_ID کار می‌کنن، تو چت خصوصی با ربات بفرست)

```
/newsignal ETH LONG 10 1800              -> بدون حد ضرر/سود
/newsignal ETH LONG 10 1800 1750         -> با حد ضرر
/newsignal ETH LONG 10 1800 1750 1950    -> با حد ضرر و حد سود

/setsl <id> <price>       تنظیم یا تغییر حد ضرر بعدا
/settp <id> <price>       تنظیم یا تغییر حد سود بعدا
/close <id> [price]       بستن دستی سیگنال
/list                     لیست سیگنال‌های باز فعلی
```

مثال واقعی که خودت گفتی:
```
/newsignal ETH LONG 10 1800
```
و بعدا هر وقت خواستی حد ضرر اضافه کنی:
```
/setsl eth-a1b2c 1750
```
(شناسه دقیق سیگنال بعد از ثبت به خودت تو پیام خصوصی گفته میشه)

## اجرای دائمی روی سرور (systemd)

یک فایل بساز: `/etc/systemd/system/toobit-bot.service`

```ini
[Unit]
Description=Toobit Telegram Signal Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/toobit_signal_bot
Environment="BOT_TOKEN=xxxx"
Environment="CHANNEL_ID=-1001234567890"
Environment="OWNER_ID=123456789"
ExecStart=/root/toobit_signal_bot/venv/bin/python3 bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

بعد:

```bash
systemctl daemon-reload
systemctl enable toobit-bot
systemctl start toobit-bot
systemctl status toobit-bot
journalctl -u toobit-bot -f
```

## نکات فنی
- منبع قیمت: وب‌سوکت رسمی توبیت (`bookTicker` استریم فیوچرز USDT-M)، میانگین best bid/ask.
- سیگنال‌ها با فرمت جفت‌ارز فیوچرز `SYMBOL-SWAP-USDT` به توبیت ساب می‌شن (مثلا `ETH-SWAP-USDT`).
- سیگنال‌های باز روی دیسک (`state.json`) ذخیره میشن، پس با ری‌استارت ربات از دست نمی‌رن.
- اگه حد ضرر یا حد سود بخوره، ربات خودش پیام رو نهایی می‌کنه و سیگنال بسته میشه.
- اگه بخوای چند سیگنال هم‌زمان (چند ارز مختلف) داشته باشی، ربات خودش همه رو به صورت موازی مدیریت می‌کنه.
