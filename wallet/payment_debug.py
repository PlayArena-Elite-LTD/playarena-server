import os


def payment_debug_enabled() -> bool:
    return os.environ.get("PAYMENT_DEBUG", "").strip().lower() in ("1", "true", "yes", "y", "on")


def mask_secret(value: str) -> str:
    if not value:
        return "(not set)"
    v = str(value)
    tail = v[-4:] if len(v) >= 4 else v
    return f"set(len={len(v)}, last4={tail})"

