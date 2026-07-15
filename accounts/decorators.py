from django.contrib.auth.decorators import user_passes_test


def is_support_staff_or_admin(user):
    """Allow support staff and Django admin staff into panel workflows."""
    return (
        user.is_authenticated
        and (
            getattr(user, 'is_support_staff', False)
            or getattr(user, 'is_staff', False)
            or getattr(user, 'is_superuser', False)
        )
    )


def support_staff_required(function=None, redirect_field_name='next', login_url='login'):
    """
    Decorator for views that require support staff or Django admin access.
    """
    actual_decorator = user_passes_test(
        is_support_staff_or_admin,
        login_url=login_url,
        redirect_field_name=redirect_field_name
    )
    if function:
        return actual_decorator(function)
    return actual_decorator
