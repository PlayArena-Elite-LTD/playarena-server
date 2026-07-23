"""
Payment notification utilities for wallet operations.

This module provides functions to create notifications for users
when payment-related events occur (withdrawals, deposits, etc.).
"""

import logging
from urllib.parse import urljoin

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from alert.models import Notification

logger = logging.getLogger(__name__)

WITHDRAWAL_ADMIN_EMAIL = 'helloplayarena@gmail.com'


def _wallet_link(url_name):
    """Build an absolute URL to a wallet page for use in emails, if a public base URL is configured."""
    base = (getattr(settings, 'PUBLIC_BASE_URL', '') or '').strip()
    if not base:
        return None
    try:
        path = reverse(url_name)
    except Exception:
        return None
    return urljoin(base.rstrip('/') + '/', path.lstrip('/'))


def _player_name(user):
    return user.get_username() or getattr(user, 'username', '') or 'Player'


def _send_wallet_email(user, subject, template_name, context):
    """Render a wallet email template and send it as HTML (with plain-text fallback)."""
    user_email = getattr(user, 'email', '') or ''
    if not user_email:
        return
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
    context.setdefault('player_name', _player_name(user))
    html_content = render_to_string(template_name, context)
    text_content = strip_tags(html_content)
    email_message = EmailMultiAlternatives(subject, text_content, from_email, [user_email])
    email_message.attach_alternative(html_content, "text/html")
    email_message.send()


def notify_withdrawal_created(withdrawal):
    """
    Send notification when a withdrawal request is created.

    Args:
        withdrawal: Withdrawal model instance
    """
    try:
        message = (
            f"Withdrawal request of ZMW {withdrawal.amount:.2f} via "
            f"{withdrawal.get_payment_method_display()} has been created and is pending approval."
        )

        Notification.objects.create(
            user=withdrawal.user,
            message=message
        )

        user_email = getattr(withdrawal.user, 'email', '') or ''
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
        if user_email:
            _send_wallet_email(
                withdrawal.user,
                subject='Withdrawal request received - PlayArena',
                template_name='emails/withdrawal_created.html',
                context={
                    'amount': f'{withdrawal.amount:.2f}',
                    'payment_method': withdrawal.get_payment_method_display(),
                    'date': timezone.localtime(withdrawal.created_at).strftime('%Y-%m-%d %H:%M'),
                },
            )

        send_mail(
            subject=f'New withdrawal request #{withdrawal.id}',
            message=(
                "A new withdrawal request has been submitted.\n\n"
                f"Withdrawal ID: {withdrawal.id}\n"
                f"User: {withdrawal.user.get_username()}\n"
                f"Email: {user_email or 'N/A'}\n"
                f"Amount: ZMW {withdrawal.amount:.2f}\n"
                f"Payment method: {withdrawal.get_payment_method_display()}\n"
                f"Account details: {withdrawal.account_details}\n"
                f"Status: {withdrawal.status}\n"
                f"Created at: {timezone.localtime(withdrawal.created_at):%Y-%m-%d %H:%M:%S %Z}"
            ),
            from_email=from_email,
            recipient_list=[WITHDRAWAL_ADMIN_EMAIL],
            fail_silently=False,
        )

        logger.info(f'Notification sent to {withdrawal.user.username} for withdrawal {withdrawal.id} creation')
    except Exception as e:
        logger.error(f'Error sending withdrawal creation notification: {str(e)}', exc_info=True)


def notify_withdrawal_processing(withdrawal):
    """
    Send notification when withdrawal processing starts.

    Args:
        withdrawal: Withdrawal model instance
    """
    try:
        message = (
            f"Your withdrawal of ZMW {withdrawal.amount:.2f} via "
            f"{withdrawal.get_payment_method_display()} is now being processed."
        )

        Notification.objects.create(
            user=withdrawal.user,
            message=message
        )

        logger.info(f'Notification sent to {withdrawal.user.username} for withdrawal {withdrawal.id} processing')
    except Exception as e:
        logger.error(f'Error sending withdrawal processing notification: {str(e)}', exc_info=True)


def notify_withdrawal_completed(withdrawal):
    """
    Send notification when withdrawal is completed successfully.

    Args:
        withdrawal: Withdrawal model instance
    """
    try:
        transaction_id = withdrawal.transaction_id or withdrawal.gateway_transaction_id or 'N/A'
        message = (
            f"Your withdrawal of ZMW {withdrawal.amount:.2f} via "
            f"{withdrawal.get_payment_method_display()} has been completed successfully. "
            f"Transaction ID: {transaction_id}"
        )

        Notification.objects.create(
            user=withdrawal.user,
            message=message
        )

        _send_wallet_email(
            withdrawal.user,
            subject='Withdrawal completed - PlayArena',
            template_name='emails/withdrawal_completed.html',
            context={
                'amount': f'{withdrawal.amount:.2f}',
                'payment_method': withdrawal.get_payment_method_display(),
                'transaction_id': transaction_id,
                'date': timezone.localtime(withdrawal.updated_at).strftime('%Y-%m-%d %H:%M'),
                'wallet_url': _wallet_link('wallet'),
            },
        )

        logger.info(f'Notification sent to {withdrawal.user.username} for withdrawal {withdrawal.id} completion')
    except Exception as e:
        logger.error(f'Error sending withdrawal completion notification: {str(e)}', exc_info=True)


def notify_withdrawal_failed(withdrawal, failure_reason=None):
    """
    Send notification when withdrawal fails.

    Args:
        withdrawal: Withdrawal model instance
        failure_reason: Optional reason for failure
    """
    try:
        reason_text = f" Reason: {failure_reason}" if failure_reason else ""
        message = (
            f"Your withdrawal of ZMW {withdrawal.amount:.2f} via "
            f"{withdrawal.get_payment_method_display()} has failed.{reason_text} "
            f"Please contact support if you need assistance."
        )

        Notification.objects.create(
            user=withdrawal.user,
            message=message
        )

        _send_wallet_email(
            withdrawal.user,
            subject='Withdrawal unsuccessful - PlayArena',
            template_name='emails/withdrawal_failed.html',
            context={
                'amount': f'{withdrawal.amount:.2f}',
                'payment_method': withdrawal.get_payment_method_display(),
                'reason': failure_reason,
                'date': timezone.localtime(withdrawal.updated_at).strftime('%Y-%m-%d %H:%M'),
                'wallet_url': _wallet_link('wallet'),
            },
        )

        logger.info(f'Notification sent to {withdrawal.user.username} for withdrawal {withdrawal.id} failure')
    except Exception as e:
        logger.error(f'Error sending withdrawal failure notification: {str(e)}', exc_info=True)


def notify_withdrawal_rejected(withdrawal, reason=None):
    """
    Send notification when a withdrawal request is rejected/cancelled by an admin.

    Args:
        withdrawal: Withdrawal model instance
        reason: Optional reason for rejection
    """
    try:
        reason_text = f" Reason: {reason}" if reason else ""
        message = (
            f"Your withdrawal request of ZMW {withdrawal.amount:.2f} via "
            f"{withdrawal.get_payment_method_display()} has been rejected.{reason_text}"
        )

        Notification.objects.create(
            user=withdrawal.user,
            message=message
        )

        _send_wallet_email(
            withdrawal.user,
            subject='Withdrawal rejected - PlayArena',
            template_name='emails/withdrawal_rejected.html',
            context={
                'amount': f'{withdrawal.amount:.2f}',
                'payment_method': withdrawal.get_payment_method_display(),
                'reason': reason,
                'date': timezone.localtime(withdrawal.updated_at).strftime('%Y-%m-%d %H:%M'),
                'wallet_url': _wallet_link('wallet'),
            },
        )

        logger.info(f'Notification sent to {withdrawal.user.username} for withdrawal {withdrawal.id} rejection')
    except Exception as e:
        logger.error(f'Error sending withdrawal rejection notification: {str(e)}', exc_info=True)


def notify_withdrawal_retry(withdrawal, retry_count, max_retries):
    """
    Send notification when withdrawal is scheduled for retry.

    Args:
        withdrawal: Withdrawal model instance
        retry_count: Current retry attempt number
        max_retries: Maximum number of retries allowed
    """
    try:
        message = (
            f"Your withdrawal of ZMW {withdrawal.amount:.2f} via "
            f"{withdrawal.get_payment_method_display()} encountered an issue and will be retried. "
            f"Attempt {retry_count} of {max_retries}. We'll notify you once it's processed."
        )

        Notification.objects.create(
            user=withdrawal.user,
            message=message
        )

        logger.info(f'Notification sent to {withdrawal.user.username} for withdrawal {withdrawal.id} retry')
    except Exception as e:
        logger.error(f'Error sending withdrawal retry notification: {str(e)}', exc_info=True)


def notify_deposit_completed(deposit):
    """
    Send notification when deposit is completed successfully.

    Args:
        deposit: Deposit model instance
    """
    try:
        transaction_id = deposit.transaction_id or 'N/A'
        message = (
            f"Your deposit of ZMW {deposit.amount:.2f} via "
            f"{deposit.get_payment_method_display()} has been completed successfully. "
            f"Transaction ID: {transaction_id}. Your wallet balance has been updated."
        )

        Notification.objects.create(
            user=deposit.user,
            message=message
        )

        completed_at = deposit.completed_at or timezone.now()
        new_balance = deposit.wallet.balance if deposit.wallet_id else None
        _send_wallet_email(
            deposit.user,
            subject='Deposit successful - PlayArena',
            template_name='emails/deposit_completed.html',
            context={
                'amount': f'{deposit.amount:.2f}',
                'payment_method': deposit.get_payment_method_display(),
                'transaction_id': transaction_id,
                'new_balance': f'{new_balance:.2f}' if new_balance is not None else 'N/A',
                'date': timezone.localtime(completed_at).strftime('%Y-%m-%d %H:%M'),
                'wallet_url': _wallet_link('wallet'),
            },
        )

        logger.info(f'Notification sent to {deposit.user.username} for deposit {deposit.id} completion')
    except Exception as e:
        logger.error(f'Error sending deposit completion notification: {str(e)}', exc_info=True)


def notify_deposit_failed(deposit, failure_reason=None):
    """
    Send notification when deposit fails.

    Args:
        deposit: Deposit model instance
        failure_reason: Optional reason for failure
    """
    try:
        reason_text = f" Reason: {failure_reason}" if failure_reason else ""
        message = (
            f"Your deposit of ZMW {deposit.amount:.2f} via "
            f"{deposit.get_payment_method_display()} has failed.{reason_text} "
            f"Please try again or contact support if the issue persists."
        )

        Notification.objects.create(
            user=deposit.user,
            message=message
        )

        _send_wallet_email(
            deposit.user,
            subject='Deposit unsuccessful - PlayArena',
            template_name='emails/deposit_failed.html',
            context={
                'amount': f'{deposit.amount:.2f}',
                'payment_method': deposit.get_payment_method_display(),
                'reason': failure_reason,
                'date': timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M'),
                'deposit_url': _wallet_link('deposit'),
            },
        )

        logger.info(f'Notification sent to {deposit.user.username} for deposit {deposit.id} failure')
    except Exception as e:
        logger.error(f'Error sending deposit failure notification: {str(e)}', exc_info=True)
