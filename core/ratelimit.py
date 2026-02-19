from functools import wraps

from django.conf import settings
from django.utils.module_loading import import_string

from django_ratelimit import ALL, UNSAFE
from django_ratelimit.core import get_usage, is_ratelimited
from django_ratelimit.exceptions import Ratelimited


def _resolve_group(fn, group):
    if group is not None:
        return group

    parts = []
    if hasattr(fn, "__module__"):
        parts.append(fn.__module__)
    if hasattr(fn, "__self__"):
        parts.append(fn.__self__.__class__.__name__)
    parts.append(fn.__qualname__)
    return ".".join(parts)


def _resolve_rate(rate, group, request):
    if callable(rate):
        return rate(group, request)
    if isinstance(rate, str) and "." in rate:
        ratefn = import_string(rate)
        return ratefn(group, request)
    return rate


def ratelimit(group=None, key=None, rate=None, method=ALL, block=True):
    """
    Wrap django-ratelimit to store timing info for a global ratelimit handler.
    """
    def decorator(fn):
        @wraps(fn)
        def _wrapped(request, *args, **kwargs):
            old_limited = getattr(request, "limited", False)
            ratelimited = is_ratelimited(
                request=request,
                group=group,
                fn=fn,
                key=key,
                rate=rate,
                method=method,
                increment=True,
            )
            request.limited = ratelimited or old_limited

            if ratelimited:
                resolved_group = _resolve_group(fn, group)
                resolved_rate = _resolve_rate(rate, resolved_group, request)
                usage = get_usage(
                    request=request,
                    group=resolved_group,
                    fn=fn,
                    key=key,
                    rate=resolved_rate,
                    method=method,
                    increment=False,
                )
                if usage:
                    request.ratelimit_info = {
                        **usage,
                        "group": resolved_group,
                        "rate": resolved_rate,
                        "key": key,
                        "method": method,
                    }

            if ratelimited and block:
                cls = getattr(settings, "RATELIMIT_EXCEPTION_CLASS", Ratelimited)
                raise (import_string(cls) if isinstance(cls, str) else cls)()

            return fn(request, *args, **kwargs)
        return _wrapped
    return decorator


ratelimit.ALL = ALL
ratelimit.UNSAFE = UNSAFE
