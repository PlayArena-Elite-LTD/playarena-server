"""
Custom error handlers for 403, 404 and 500 errors.
"""
from django.http import JsonResponse
from django.shortcuts import render
from django_ratelimit.exceptions import Ratelimited


def _format_wait_time(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    minutes, remaining = divmod(seconds, 60)
    if minutes < 60:
        unit = "minute" if minutes == 1 else "minutes"
        if remaining:
            return f"{minutes} {unit} {remaining} seconds"
        return f"{minutes} {unit}"
    hours, minutes = divmod(minutes, 60)
    unit = "hour" if hours == 1 else "hours"
    if minutes:
        return f"{hours} {unit} {minutes} minutes"
    return f"{hours} {unit}"


def handler403(request, exception):
    """Custom 403 error handler with rate limit details when available."""
    ratelimit_info = getattr(request, "ratelimit_info", None)
    is_ratelimited = isinstance(exception, Ratelimited) or getattr(request, "limited", False)

    if is_ratelimited:
        time_left = 0
        limit = None
        if ratelimit_info:
            time_left = ratelimit_info.get("time_left", 0) or 0
            limit = ratelimit_info.get("limit")

        retry_after = max(0, int(time_left))
        payload = {
            "detail": "Too many attempts. Please try again later.",
            "retry_after": retry_after,
            "retry_after_human": _format_wait_time(retry_after),
            "limit": limit,
        }

        accepts_json = "application/json" in request.headers.get("accept", "")
        if request.path.startswith("/api/") or accepts_json:
            response = JsonResponse(payload, status=429)
        else:
            response = render(
                request,
                "429.html",
                {
                    "retry_after": retry_after,
                    "retry_after_human": payload["retry_after_human"],
                },
                status=429,
            )
        if retry_after:
            response["Retry-After"] = str(retry_after)
        return response

    return render(request, "403.html", status=403)


def handler404(request, exception):
    """Custom 404 error handler"""
    return render(request, '404.html', status=404)


def handler500(request):
    """Custom 500 error handler"""
    return render(request, '500.html', status=500)
