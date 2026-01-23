# Quick Start Guide - Running the Application

## Option 1: If Using Pipenv (recommended if Pipfile exists)

1. **Install dependencies and activate virtual environment:**
   ```bash
   pipenv install
   pipenv shell
   ```

2. **Create cache table:**
   ```bash
   python manage.py createcachetable
   ```

3. **Run migrations (if needed):**
   ```bash
   python manage.py migrate
   ```

4. **Start the server:**
   ```bash
   python manage.py runserver
   ```

## Option 2: If Using Standard Python/Pip

1. **Create a virtual environment (recommended):**
   ```bash
   python -m venv venv
   ```

2. **Activate the virtual environment:**
   - **Windows PowerShell:**
     ```powershell
     .\venv\Scripts\Activate.ps1
     ```
   - **Windows Command Prompt:**
     ```cmd
     venv\Scripts\activate.bat
     ```
   - **Linux/Mac:**
     ```bash
     source venv/bin/activate
     ```

3. **Install dependencies:**
   ```bash
   python -m pip install -r requirements.txt
   ```

4. **Create cache table:**
   ```bash
   python manage.py createcachetable
   ```

5. **Run migrations:**
   ```bash
   python manage.py migrate
   ```

6. **Start the server:**
   ```bash
   python manage.py runserver
   ```

## After Starting the Server

The application will be available at: **http://127.0.0.1:8000/**

### Access Points:
- Home: http://127.0.0.1:8000/
- Login: http://127.0.0.1:8000/accounts/login/
- Wallet: http://127.0.0.1:8000/wallet/ (requires login)
- Matches: http://127.0.0.1:8000/matches/

## Testing Rate Limits

### Test Login (5 attempts per 15 minutes):
- Try logging in with wrong credentials 6 times
- You should see: "Too many login attempts. Please wait 15 minutes before trying again."

### Test Registration (3 per hour):
- Go to `/accounts/pre-signup/` and submit 4 times
- You should see: "Too many registration attempts. Please wait 1 hour before trying again."

### Test Wallet Operations:
- After logging in, try making 11 deposits in 1 minute or 6 withdrawals in 1 hour
- You'll see appropriate rate limit error messages

## Check Logs

Rate limit violations are logged to: `rate_limit.log` in your project directory

## Troubleshooting

**If you get "ModuleNotFoundError: No module named 'django'":**
- Make sure you've activated your virtual environment
- Run: `python -m pip install -r requirements.txt`

**If cache table creation fails:**
- Make sure you've run migrations first: `python manage.py migrate`
- Then try: `python manage.py createcachetable` again

**To reset rate limits during testing:**
```bash
python manage.py shell
>>> from django.core.cache import cache
>>> cache.clear()
>>> exit()
```











