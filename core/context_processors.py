from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.utils import timezone
from django.core.cache import caches
import os


def environment_label(_request):
    """
    Expose runtime and admin KPI values for templates.
    """
    label = "Production" if not settings.DEBUG else "Development"

    # These KPIs are surprisingly expensive (especially online_users, which decodes
    # all active sessions). In development, keep the page snappy by default.
    enable_kpis = (not settings.DEBUG) or (
        str(os.environ.get("ENABLE_TEMPLATE_KPIS", "")).strip().lower() in ("1", "true", "yes", "y", "on")
    )
    if not enable_kpis:
        return {
            "environment_label": label,
        }

    # Use an in-process cache (ratelimit cache is LocMem) to avoid Redis dependency in dev.
    cache = caches["ratelimit"]

    total_users = cache.get("kpi_total_users")
    if total_users is None:
        total_users = get_user_model().objects.count()
        cache.set("kpi_total_users", total_users, 60)

    online_users = cache.get("kpi_online_users")
    if online_users is None:
        now = timezone.now()
        sessions = Session.objects.filter(expire_date__gt=now)
        user_ids = set()
        for session in sessions:
            data = session.get_decoded()
            user_id = data.get("_auth_user_id")
            if user_id:
                user_ids.add(user_id)
        online_users = len(user_ids)
        cache.set("kpi_online_users", online_users, 30)

    return {
        "environment_label": label,
        "online_users": online_users,
        "total_users": total_users,
    }
