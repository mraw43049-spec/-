"""
اعتبارسنجی initData تلگرام.

وقتی مینی‌اپ داخل تلگرام باز می‌شه، تلگرام یه رشته‌ی امضاشده (initData) به فرانت‌اند
می‌ده. فرانت‌اند همون رشته رو عیناً برای بک‌اند می‌فرسته و اینجا با الگوریتم رسمی
تلگرام (HMAC-SHA256 بر پایه‌ی توکن بات) چک می‌کنیم که واقعاً جعلی نیست.
مستندات رسمی: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400):
    """
    اگه initData معتبر باشه، دیکشنری پارس‌شده‌شو برمی‌گردونه (شامل کلید 'user').
    اگه نامعتبر/جعلی/قدیمی باشه، None برمی‌گردونه.
    """
    if not init_data:
        return None
    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        return None

    # جلوگیری از replay attack: اگه initData خیلی قدیمی باشه قبولش نمی‌کنیم.
    auth_date = parsed.get("auth_date")
    if auth_date:
        try:
            if time.time() - int(auth_date) > max_age_seconds:
                return None
        except ValueError:
            return None

    return parsed


def extract_telegram_user(parsed_init_data: dict):
    """از خروجی validate_init_data، دیکشنری کاربر تلگرامی (id, first_name, username, ...) رو درمیاره."""
    raw_user = parsed_init_data.get("user")
    if not raw_user:
        return None
    try:
        return json.loads(raw_user)
    except (TypeError, ValueError):
        return None
