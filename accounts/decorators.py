from django.contrib.auth.decorators import user_passes_test

def support_staff_required(function=None, redirect_field_name='next', login_url='login'):
    """
    Decorator for views that checks that the user is support staff,
    redirects to the log-in page if necessary.
    """
    actual_decorator = user_passes_test(
        lambda u: u.is_authenticated and getattr(u, 'is_support_staff', False),
        login_url=login_url,
        redirect_field_name=redirect_field_name
    )
    if function:
        return actual_decorator(function)
    return actual_decorator