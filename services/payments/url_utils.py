"""URL helpers for payment callbacks (no wallet model imports)."""
from urllib.parse import urljoin

from django.conf import settings


def build_public_url(request, path_or_url: str) -> str:
    public_base = (getattr(settings, 'PUBLIC_BASE_URL', '') or '').strip()
    if public_base:
        return urljoin(public_base, path_or_url)
    return request.build_absolute_uri(path_or_url)
