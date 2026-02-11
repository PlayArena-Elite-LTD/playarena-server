#!/usr/bin/env python
"""
Check current Django settings configuration.
"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django
django.setup()

from django.conf import settings

print("=== Current Django Configuration ===")
print(f"DEBUG: {settings.DEBUG}")
print(f"RATELIMIT_ENABLE: {settings.RATELIMIT_ENABLE}")
print(f"Cache backend: {settings.CACHES['default']['BACKEND']}")

# Test if Redis is available
try:
    import redis
    r = redis.Redis(host='127.0.0.1', port=6379, db=1, socket_connect_timeout=2)
    r.ping()
    print("Redis: ✅ Available")
except:
    print("Redis: ❌ Not available")

# Test rate limiting functionality
from django.test import Client
from django.urls import reverse

print("\n=== Testing Rate Limiting ===")
client = Client()
login_url = reverse('login')

print("Testing login endpoint (5/m limit):")
for i in range(7):
    response = client.post(login_url, {
        'username': 'test@example.com',
        'password': 'testpass123'
    })
    print(f"  Attempt {i+1}: {response.status_code}")
    if response.status_code == 429:
        print("  ✅ Rate limiting activated!")
        break
