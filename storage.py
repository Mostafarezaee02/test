"""
ذخیره و بازیابی سیگنال‌ها روی دیسک (فایل JSON ساده، نوشتن اتمیک با os.replace)
تا اگه ربات ری‌استارت شد سیگنال‌های باز از دست نرن
"""

import json
import logging
import os

from config import STATE_FILE
from signal_model import Signal

log = logging.getLogger("storage")


def load_signals() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {sid: Signal.from_dict(sdata) for sid, sdata in raw.items()}
    except Exception:
        log.exception("خطا در خواندن فایل وضعیت — با لیست خالی شروع می‌شه")
        return {}


def save_signals(signals: dict):
    try:
        raw = {sid: sig.to_dict() for sid, sig in signals.items()}
        tmp_path = STATE_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, STATE_FILE)   # نوشتن اتمیک — هیچوقت فایل نصفه‌نوشته نمی‌مونه
    except Exception:
        log.exception("خطا در ذخیره فایل وضعیت")
