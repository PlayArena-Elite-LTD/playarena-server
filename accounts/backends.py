from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

User = get_user_model()

class EmailOrUsernameModelBackend(ModelBackend):
    """
    Authentication backend which allows users to authenticate using either their
    username or email address
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        # Check if the input contains '@' to determine if it's an email
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)

        if username is None or password is None:
            return None

        try:
            # Try to fetch the user based on either username or email
            user = User.objects.get(
                Q(username__iexact=username) | Q(email__iexact=username)
            )

            # Check the password
            if user.check_password(password) and self.user_can_authenticate(user):
                return user

        except User.DoesNotExist:
            # Run the default password hasher once to reduce timing
            # attacks against non-existent users
            User().set_password(password)

        return None