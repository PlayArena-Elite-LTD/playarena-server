"""
Payment notification utilities for wallet operations.

This module provides functions to create notifications for users
when payment-related events occur (withdrawals, deposits, etc.).
"""

import logging
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from alert.models import Notification

logger = logging.getLogger(__name__)

WITHDRAWAL_ADMIN_EMAIL = 'josephmbuzi9@gmail.com'


def notify_withdrawal_created(withdrawal):
    """
    Send notification when a withdrawal request is created.
    
    Args:
        withdrawal: Withdrawal model instance
    """
    try:
        message = (
            f"Withdrawal request of ${withdrawal.amount:.2f} via "
            f"{withdrawal.get_payment_method_display()} has been created and is pending approval."
        )
        
        Notification.objects.create(
            user=withdrawal.user,
            message=message
        )

        user_email = getattr(withdrawal.user, 'email', '') or ''
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
        if user_email:
            send_mail(
                subject='Withdrawal request received',
                message=(
                    f"Hi {withdrawal.user.get_username()},\n\n"
                    f"We received your withdrawal request for ${withdrawal.amount:.2f} via "
                    f"{withdrawal.get_payment_method_display()}.\n\n"
                    "Your request is pending review. Your wallet will be debited only after "
                    "the withdrawal is completed.\n\n"
                    f"Withdrawal ID: {withdrawal.id}"
                ),
                from_email=from_email,
                recipient_list=[user_email],
                fail_silently=False,
            )

        send_mail(
            subject=f'New withdrawal request #{withdrawal.id}',
            message=(
                "A new withdrawal request has been submitted.\n\n"
                f"Withdrawal ID: {withdrawal.id}\n"
                f"User: {withdrawal.user.get_username()}\n"
                f"Email: {user_email or 'N/A'}\n"
                f"Amount: ${withdrawal.amount:.2f}\n"
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
            f"Your withdrawal of ${withdrawal.amount:.2f} via "
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
            f"Your withdrawal of ${withdrawal.amount:.2f} via "
            f"{withdrawal.get_payment_method_display()} has been completed successfully. "
            f"Transaction ID: {transaction_id}"
        )
        
        Notification.objects.create(
            user=withdrawal.user,
            message=message
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
            f"Your withdrawal of ${withdrawal.amount:.2f} via "
            f"{withdrawal.get_payment_method_display()} has failed.{reason_text} "
            f"Please contact support if you need assistance."
        )
        
        Notification.objects.create(
            user=withdrawal.user,
            message=message
        )
        
        logger.info(f'Notification sent to {withdrawal.user.username} for withdrawal {withdrawal.id} failure')
    except Exception as e:
        logger.error(f'Error sending withdrawal failure notification: {str(e)}', exc_info=True)


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
            f"Your withdrawal of ${withdrawal.amount:.2f} via "
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
            f"Your deposit of ${deposit.amount:.2f} via "
            f"{deposit.get_payment_method_display()} has been completed successfully. "
            f"Transaction ID: {transaction_id}. Your wallet balance has been updated."
        )
        
        Notification.objects.create(
            user=deposit.user,
            message=message
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
            f"Your deposit of ${deposit.amount:.2f} via "
            f"{deposit.get_payment_method_display()} has failed.{reason_text} "
            f"Please try again or contact support if the issue persists."
        )
        
        Notification.objects.create(
            user=deposit.user,
            message=message
        )
        
        logger.info(f'Notification sent to {deposit.user.username} for deposit {deposit.id} failure')
    except Exception as e:
        logger.error(f'Error sending deposit failure notification: {str(e)}', exc_info=True)
