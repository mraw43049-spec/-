"""Telegram Mini App initData verification helpers."""
import hashlib
import hmac
import json
from urllib.parse import parse_qsl

def validate_init_data(init_data: str, bot_token: str):
    """Validate Telegram WebApp initData and return its parsed fields, or None."""
    if not init_data or not bot_token:
        return None
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        received_hash = data.pop("hash", None)
        if not received_hash:
            return None
        check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            return None
        # Reject stale initData older than 24 hours.
        import time
        auth_date = int(data.get("auth_date", "0"))
        if auth_date <= 0 or time.time() - auth_date > 86400 or auth_date - time.time() > 60:
            return None
        return data
    except (ValueError, TypeError):
        return None

def extract_telegram_user(parsed):
    """Decode the JSON user field from validated Telegram initData."""
    try:
        user = json.loads(parsed.get("user", ""))
        return user if isinstance(user, dict) else None
    except (ValueError, TypeError, AttributeError):
        return None
