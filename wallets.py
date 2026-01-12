#!/usr/bin/env python
import os
import django
import sys

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')  # Replace with your project settings
django.setup()

from django.contrib.auth import get_user_model
from wallet.models import Wallet
from django.db import transaction

def create_wallets_for_existing_users():
    User = get_user_model()
    users_without_wallets = User.objects.filter(wallet__isnull=True)
    
    print(f"Found {users_without_wallets.count()} users without wallets")
    
    with transaction.atomic():
        wallets_created = 0
        for user in users_without_wallets:
            Wallet.objects.create(user=user)
            wallets_created += 1
            print(f"Created wallet for {user.username}")
    
    print(f"\nSuccessfully created {wallets_created} wallets")
    print(f"Current date: 2025-04-12 10:30:01")
    print(f"Current user: luke-16")

if __name__ == "__main__":
    create_wallets_for_existing_users()