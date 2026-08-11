"""OneSignal web-push helper.

Sends a push to specific users via their OneSignal *external id* (which the
frontend sets to the PlayArena user id on login). Fully guarded: a no-op when
OneSignal isn't configured, and never raises into the caller.
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

ONESIGNAL_API_URL = 'https://onesignal.com/api/v1/notifications'


def push_enabled():
    return bool(
        getattr(settings, 'ONESIGNAL_APP_ID', '')
        and getattr(settings, 'ONESIGNAL_REST_API_KEY', '')
    )


def _absolute_url(link):
    if not link:
        return None
    if link.startswith('http://') or link.startswith('https://'):
        return link
    origin = getattr(settings, 'FRONTEND_ORIGIN', '') or ''
    return f"{origin}{link}" if origin else None


def send_push(external_user_ids, message, heading=None, url=None):
    """Send a push notification to the given PlayArena user ids (external ids)."""
    if not push_enabled():
        return
    ids = [str(uid) for uid in external_user_ids if uid]
    if not ids:
        return

    payload = {
        'app_id': settings.ONESIGNAL_APP_ID,
        'include_external_user_ids': ids,
        'channel_for_external_user_ids': 'push',
        'contents': {'en': message},
    }
    if heading:
        payload['headings'] = {'en': heading}
    absolute = _absolute_url(url)
    if absolute:
        payload['url'] = absolute

    try:
        resp = requests.post(
            ONESIGNAL_API_URL,
            json=payload,
            headers={
                'Authorization': f"Basic {settings.ONESIGNAL_REST_API_KEY}",
                'Content-Type': 'application/json; charset=utf-8',
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.warning('OneSignal push failed (%s): %s', resp.status_code, resp.text[:300])
    except Exception as exc:  # noqa: BLE001 — push must never break app flow
        logger.warning('OneSignal push error: %s', exc)
