from django.contrib.auth import get_user_model
from accounts.models import Profile

User = get_user_model()

# Get all users
users = User.objects.all()

# Create profiles for users without them
for user in users:
    try:
        # Check if profile exists by accessing it
        profile = user.profile
        print(f"Profile exists for {user.username}")
    except:
        # Create profile if it doesn't exist
        profile = Profile.objects.create(user=user)
        print(f"Created profile for {user.username}")