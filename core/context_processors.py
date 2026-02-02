from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.utils import timezone


def environment_label(_request):
    """
    Expose runtime and admin KPI values for templates.
    """
    now = timezone.now()
    sessions = Session.objects.filter(expire_date__gt=now)
    user_ids = set()
    for session in sessions:
        data = session.get_decoded()
        user_id = data.get("_auth_user_id")
        if user_id:
            user_ids.add(user_id)

    return {
        "environment_label": "Production" if not settings.DEBUG else "Development",
        "online_users": len(user_ids),
        "total_users": get_user_model().objects.count(),
    }
