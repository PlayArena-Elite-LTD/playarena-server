# How to Run the Application with Rate Limiting

## Step 1: Install Dependencies

First, install the django-ratelimit package:

```bash
python -m pip install django-ratelimit
```

Or install all requirements:
```bash
python -m pip install -r requirements.txt
```

## Step 2: Create Cache Table

Rate limiting uses the database cache, so you need to create the cache table:

```bash
python manage.py createcachetable
```

This will create the `django_cache_table` in your database for storing rate limit data.

## Step 3: Run Migrations (if needed)

Make sure your database is up to date:

```bash
python manage.py migrate
```

## Step 4: Start the Development Server

Run the Django development server:

```bash
python manage.py runserver
```

The server will start at `http://127.0.0.1:8000/`

## Step 5: Access the Application

Open your browser and go to:
- Main page: `http://127.0.0.1:8000/`
- Login: `http://127.0.0.1:8000/accounts/login/`
- Wallet: `http://127.0.0.1:8000/wallet/` (requires login)

## Testing Rate Limits

To test that rate limiting is working:

### Test Login Rate Limit (5 attempts per 15 minutes):
1. Go to `/accounts/login/`
2. Try logging in with wrong credentials 6 times
3. On the 6th attempt, you should see: "Too many login attempts. Please wait 15 minutes before trying again."

### Test Registration Rate Limit (3 per hour):
1. Go to `/accounts/pre-signup/`
2. Submit the form 4 times
3. On the 4th attempt, you should see: "Too many registration attempts. Please wait 1 hour before trying again."

### Test Wallet Rate Limits:
1. Login to your account
2. Go to `/wallet/`
3. Try making 11 deposit requests in 1 minute (or 6 withdrawals in 1 hour)
4. You should see appropriate rate limit messages

## Check Rate Limit Logs

Rate limit violations are logged to `rate_limit.log` in your project root directory.

## Important Notes

- Rate limits are stored in the database cache table
- If you want to reset rate limits during testing, you can clear the cache:
  ```bash
  python manage.py shell
  >>> from django.core.cache import cache
  >>> cache.clear()
  ```
- The rate limit logs are stored in `rate_limit.log` file in your project directory











