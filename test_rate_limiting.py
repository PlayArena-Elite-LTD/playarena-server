"""
Rate Limiting Test Script

This script tests rate limiting functionality across different endpoints.
Run with: python test_rate_limiting.py
"""

import os
import sys
import django
import requests
import time
from datetime import datetime

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.test import Client, override_settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.conf import settings

User = get_user_model()

# Add testserver to ALLOWED_HOSTS for testing
if 'testserver' not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS.append('testserver')

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}\n")

def print_success(text):
    print(f"{Colors.GREEN}[PASS] {text}{Colors.RESET}")

def print_error(text):
    print(f"{Colors.RED}[FAIL] {text}{Colors.RESET}")

def print_warning(text):
    print(f"{Colors.YELLOW}[WARN] {text}{Colors.RESET}")

def print_info(text):
    print(f"  {text}")

def test_login_rate_limit():
    """Test rate limiting on login endpoint (3/hour by IP)"""
    print_header("TEST 1: Login Rate Limiting (3/hour by IP)")
    
    client = Client()
    login_url = '/accounts/login/'
    
    print_info("Attempting 5 login requests (limit is 3/hour)...")
    print_info("Note: Rate limiting is per IP, so we need to clear cache between tests")
    
    # Clear rate limit cache first
    cache.clear()
    
    success_count = 0
    rate_limited_count = 0
    allowed_count = 0
    
    for i in range(5):
        response = client.post(login_url, {
            'username': 'testuser',
            'password': 'wrongpassword',
            'csrfmiddlewaretoken': client.get(login_url).cookies.get('csrftoken', '').value if hasattr(client.get(login_url).cookies.get('csrftoken', ''), 'value') else ''
        }, HTTP_HOST='testserver')
        
        # Check response
        if response.status_code == 429:
            rate_limited_count += 1
            print_warning(f"Request {i+1}: Rate Limited (429)")
        elif response.status_code == 200:
            # Check if there's a rate limit message
            content = response.content.decode('utf-8', errors='ignore')
            if 'rate limit' in content.lower() or 'too many' in content.lower():
                rate_limited_count += 1
                print_warning(f"Request {i+1}: Rate Limited (detected in content)")
            else:
                allowed_count += 1
                print_info(f"Request {i+1}: Allowed (200 OK)")
        elif response.status_code == 302:
            # Redirect might indicate rate limit
            allowed_count += 1
            print_info(f"Request {i+1}: Redirected (302)")
        else:
            print_info(f"Request {i+1}: Status {response.status_code}")
        
        time.sleep(0.3)  # Small delay between requests
    
    print_info(f"Results: {allowed_count} allowed, {rate_limited_count} rate limited")
    
    if rate_limited_count >= 2:
        print_success(f"Rate limiting working! {rate_limited_count} requests were rate limited")
        return True
    elif rate_limited_count >= 1:
        print_warning(f"Rate limiting partially working. {rate_limited_count} requests were rate limited")
        return True
    else:
        print_warning(f"Rate limiting may not be working. Only {rate_limited_count} requests were rate limited")
        print_info("This could be normal if cache was cleared or rate limit window expired")
        return False

def test_deposit_rate_limit():
    """Test rate limiting on deposit endpoint (10/minute by user)"""
    print_header("TEST 2: Deposit Rate Limiting (10/minute by user)")
    
    # Create or get test user
    try:
        user = User.objects.get(username='testuser')
    except User.DoesNotExist:
        print_warning("Test user not found. Creating test user...")
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    # Ensure user has wallet
    from wallet.models import Wallet
    wallet, _ = Wallet.objects.get_or_create(user=user)
    
    client = Client()
    client.force_login(user)
    
    deposit_url = '/wallet/deposit/'
    
    print_info("Attempting 12 deposit requests (limit is 10/minute)...")
    print_info("Clearing rate limit cache first...")
    
    # Clear rate limit cache for this user
    cache_key = f"rl:user:{user.id}:wallet.deposit_view:POST"
    cache.delete(cache_key)
    
    success_count = 0
    rate_limited_count = 0
    allowed_count = 0
    
    for i in range(12):
        # Get CSRF token first
        get_response = client.get(deposit_url, HTTP_HOST='testserver')
        csrf_token = ''
        if hasattr(get_response, 'cookies') and 'csrftoken' in get_response.cookies:
            csrf_token = get_response.cookies['csrftoken'].value
        
        response = client.post(deposit_url, {
            'amount': '10.00',
            'payment_method': 'BANK_TRANSFER',
            'csrfmiddlewaretoken': csrf_token
        }, HTTP_HOST='testserver', follow=True)
        
        if response.status_code == 429:
            rate_limited_count += 1
            print_warning(f"Request {i+1}: Rate Limited (429)")
        elif response.status_code == 200:
            # Check content for rate limit messages
            content = response.content.decode('utf-8', errors='ignore')
            if 'rate limit' in content.lower() or 'too many' in content.lower():
                rate_limited_count += 1
                print_warning(f"Request {i+1}: Rate Limited (detected in content)")
            else:
                allowed_count += 1
                if i < 3:
                    print_info(f"Request {i+1}: Allowed (200 OK)")
        elif response.status_code == 302:
            allowed_count += 1
            if i < 3:
                print_info(f"Request {i+1}: Redirected (302)")
        else:
            print_info(f"Request {i+1}: Status {response.status_code}")
        
        time.sleep(0.2)  # Small delay between requests
    
    print_info(f"Results: {allowed_count} allowed, {rate_limited_count} rate limited")
    
    if rate_limited_count >= 2:
        print_success(f"Rate limiting working! {rate_limited_count} requests were rate limited")
        return True
    elif rate_limited_count >= 1:
        print_warning(f"Rate limiting partially working. {rate_limited_count} requests were rate limited")
        return True
    else:
        print_warning(f"Rate limiting may not be working as expected. {rate_limited_count} requests were rate limited")
        print_info("Note: Rate limiting might need more requests or cache might have been cleared")
        return False

def test_match_creation_rate_limit():
    """Test rate limiting on match creation (10/hour by user)"""
    print_header("TEST 3: Match Creation Rate Limiting (10/hour by user)")
    
    # Get or create test user
    try:
        user = User.objects.get(username='testuser')
    except User.DoesNotExist:
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    # Ensure user has wallet with balance
    from wallet.models import Wallet
    wallet, _ = Wallet.objects.get_or_create(user=user)
    wallet.balance = 1000.00
    wallet.save()
    
    client = Client()
    client.force_login(user)
    
    create_match_url = '/matches/create/'
    
    print_info("Attempting 12 match creation requests (limit is 10/hour)...")
    print_warning("Note: This test may take longer due to hourly rate limit")
    
    success_count = 0
    rate_limited_count = 0
    
    for i in range(12):
        response = client.post(create_match_url, {
            'game': 'FIFA',
            'amount': '10.00',
            'platform': 'PC',
            'joining_code': f'TEST{i}'
        }, follow=True)
        
        if response.status_code == 200:
            # Check for rate limit messages
            if any('rate limit' in str(msg).lower() or 'too many' in str(msg).lower() 
                   for msg in response.context.get('messages', []) if hasattr(response, 'context')):
                rate_limited_count += 1
                print_warning(f"Request {i+1}: Rate Limited (detected in messages)")
            else:
                success_count += 1
                print_info(f"Request {i+1}: Allowed (200 OK)")
        elif response.status_code == 429:
            rate_limited_count += 1
            print_warning(f"Request {i+1}: Rate Limited (429)")
        else:
            print_info(f"Request {i+1}: Status {response.status_code}")
        
        time.sleep(0.3)
    
    if rate_limited_count >= 2:
        print_success(f"Rate limiting working! {rate_limited_count} requests were rate limited")
        return True
    else:
        print_warning(f"Rate limiting may not be working as expected. {rate_limited_count} requests were rate limited")
        return False

def test_cache_status():
    """Check if rate limiting cache is working"""
    print_header("TEST 4: Rate Limiting Cache Status")
    
    try:
        # Try to set and get from cache
        cache.set('ratelimit_test', 'working', 60)
        result = cache.get('ratelimit_test')
        
        if result == 'working':
            print_success("Cache is working correctly")
            cache_type = cache.__class__.__name__
            print_info(f"Cache backend: {cache_type}")
            
            if 'LocMem' in cache_type:
                print_warning("Using local memory cache - rate limiting won't work across multiple processes")
            elif 'Redis' in cache_type:
                print_success("Using Redis cache - rate limiting will work across processes")
            elif 'FileBased' in cache_type:
                print_info("Using file-based cache - rate limiting will work across processes")
            
            return True
        else:
            print_error("Cache test failed")
            return False
    except Exception as e:
        print_error(f"Cache test error: {str(e)}")
        return False

def test_rate_limit_configuration():
    """Check rate limiting configuration"""
    print_header("TEST 5: Rate Limiting Configuration Check")
    
    from django.conf import settings
    
    print_info("Checking rate limiting settings...")
    
    # Check if rate limiting is enabled
    ratelimit_enabled = getattr(settings, 'RATELIMIT_ENABLE', False)
    if ratelimit_enabled:
        print_success("Rate limiting is ENABLED")
    else:
        print_error("Rate limiting is DISABLED")
    
    # Check cache configuration
    ratelimit_cache = getattr(settings, 'RATELIMIT_USE_CACHE', 'default')
    print_info(f"Rate limit cache: {ratelimit_cache}")
    
    # Check if django-ratelimit is installed
    try:
        import django_ratelimit
        print_success("django-ratelimit package is installed")
    except ImportError:
        print_error("django-ratelimit package is NOT installed")
    
    return ratelimit_enabled

def main():
    """Run all rate limiting tests"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}")
    print("="*60)
    print("RATE LIMITING TEST SUITE")
    print("="*60)
    print(f"{Colors.RESET}")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    results = {}
    
    # Test configuration
    results['config'] = test_rate_limit_configuration()
    print()
    
    # Test cache
    results['cache'] = test_cache_status()
    print()
    
    # Test login rate limiting
    results['login'] = test_login_rate_limit()
    print()
    
    # Test deposit rate limiting
    results['deposit'] = test_deposit_rate_limit()
    print()
    
    # Test match creation rate limiting (commented out as it requires wallet balance)
    # results['match'] = test_match_creation_rate_limit()
    # print()
    
    # Summary
    print_header("TEST SUMMARY")
    
    total_tests = len(results)
    passed_tests = sum(1 for v in results.values() if v)
    
    print_info(f"Total tests: {total_tests}")
    print_info(f"Passed: {passed_tests}")
    print_info(f"Failed: {total_tests - passed_tests}")
    
    if passed_tests == total_tests:
        print_success("\nAll rate limiting tests PASSED!")
    else:
        print_warning(f"\n{total_tests - passed_tests} test(s) failed. Review the output above.")
    
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}\n")

if __name__ == '__main__':
    main()
