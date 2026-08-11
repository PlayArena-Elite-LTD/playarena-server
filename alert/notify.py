"""Unified notification + email helper for tournament (and general) events.

`notify(...)` always creates an in-app Notification, and optionally sends an
email. Email sending is deferred to `transaction.on_commit`, so:
  * an email is only ever sent if the surrounding transaction commits, and
  * a mail-server failure can never break the request or poison a transaction.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

from .models import Notification

logger = logging.getLogger(__name__)


def _send_email_safe(email, subject, body):
    try:
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', '') or None
        send_mail(subject, body, from_email, [email], fail_silently=True)
    except Exception as exc:  # noqa: BLE001 — email must never break app flow
        logger.warning("Failed to send notification email to %s: %s", email, exc)


def notify(user, message, link='/tournaments', *, email=False, subject=None, push=True):
    """Create an in-app notification; optionally queue a push and an email.

    Push and email are deferred to `transaction.on_commit`, so they only fire if
    the surrounding transaction commits and can never break the request.
    """
    notification = Notification.objects.create(user=user, message=message, link=link)
    heading = subject or 'PlayArena'

    user_id = getattr(user, 'id', None)
    if push and user_id:
        from .push import send_push

        def _queue_push():
            send_push([user_id], message, heading=heading, url=link)

        transaction.on_commit(_queue_push)

    if email and getattr(user, 'email', ''):
        recipient = user.email

        def _queue_email():
            _send_email_safe(recipient, heading, message)

        transaction.on_commit(_queue_email)

    return notification
