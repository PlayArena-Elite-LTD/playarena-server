# Pesapal Development Setup Guide

This guide explains how to configure Pesapal for local development.

## Development Options

You have **two options** for developing with Pesapal:

### Option 1: Mock Mode (Recommended for Local Development)

**Best for:** Local development without internet connection or Pesapal account

Mock mode allows you to test the payment flow without making real API calls to Pesapal. Deposits will automatically complete when the callback is triggered.

**Setup:**
```bash
# In your .env file
PESAPAL_MOCK_MODE=true
PESAPAL_CONSUMER_KEY=  # Can be empty in mock mode
PESAPAL_CONSUMER_SECRET=  # Can be empty in mock mode
PESAPAL_BASE_URL=https://cybqa.pesapal.com/pesapalv3  # Not used in mock mode
PESAPAL_IPN_ID=  # Not needed in mock mode
```

**How it works:**
- When `PESAPAL_MOCK_MODE=true`, the system skips real Pesapal API calls
- Deposits are automatically marked as completed when callback/IPN is triggered
- Order tracking IDs will start with `MOCK_` prefix
- No real payment processing occurs

**Testing:**
1. Create a deposit in your app
2. You'll get a mock redirect URL
3. When you visit the callback URL, the deposit auto-completes
4. No actual payment is processed

---

### Option 2: Pesapal Sandbox/Test Environment

**Best for:** Testing real API integration before production

Use Pesapal's sandbox environment to test the actual API integration.

#### Step 1: Get Pesapal Sandbox Credentials

1. **Sign up for Pesapal Developer Account:**
   - Go to: https://developer.pesapal.com/
   - Create an account (if you don't have one)
   - Log in to the developer dashboard

2. **Create a Sandbox Application:**
   - Navigate to "My Apps" or "Applications"
   - Create a new application for sandbox/testing
   - You'll receive:
     - **Consumer Key** (also called Consumer Key)
     - **Consumer Secret** (also called Consumer Secret)

3. **Get Sandbox Credentials:**
   - Sandbox credentials are different from production credentials
   - Look for "Sandbox" or "Test" environment credentials
   - These are safe to use in development

#### Step 2: Configure Your .env File

```bash
# Pesapal Sandbox Configuration
PESAPAL_CONSUMER_KEY=your_sandbox_consumer_key_here
PESAPAL_CONSUMER_SECRET=your_sandbox_consumer_secret_here
PESAPAL_BASE_URL=https://cybqa.pesapal.com/pesapalv3
PESAPAL_MOCK_MODE=false  # or leave empty

# IPN Configuration (Optional for local dev)
# For local development, you may need to use a tunnel (ngrok, Cloudflare Tunnel)
# See "Local Development with IPN" section below
PESAPAL_IPN_ID=  # Leave empty initially, will be auto-registered
PUBLIC_BASE_URL=http://localhost:8000  # Your public URL for callbacks
```

#### Step 3: Test Your Configuration

```bash
# Check if Pesapal is configured correctly
python manage.py check_pesapal_config
```

This will show:
- Whether consumer key/secret are set (masked for security)
- Base URL configuration
- IPN ID status

---

## Local Development with IPN (Instant Payment Notification)

Pesapal requires a publicly accessible URL for IPN callbacks. For local development, you have two options:

### Option A: Use Mock Mode (Easiest)
```bash
PESAPAL_MOCK_MODE=true
```
No IPN setup needed - deposits auto-complete.

### Option B: Use a Tunnel (For Real API Testing)

1. **Set up a tunnel** (choose one):
   - **ngrok:** `ngrok http 8000`
   - **Cloudflare Tunnel:** `cloudflared tunnel --url http://localhost:8000`
   - **localtunnel:** `npx localtunnel --port 8000`

2. **Update your .env:**
   ```bash
   PUBLIC_BASE_URL=https://your-tunnel-url.ngrok.io
   PESAPAL_MOCK_MODE=false
   ```

3. **Register IPN automatically:**
   The system will automatically register the IPN URL when you create your first deposit, or you can manually register:
   ```bash
   python manage.py register_pesapal_ipn --url "https://your-tunnel-url.ngrok.io/wallet/webhooks/pesapal/"
   ```

---

## Environment Variables Reference

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `PESAPAL_CONSUMER_KEY` | Yes* | Your Pesapal consumer key | `qkio1B2...` |
| `PESAPAL_CONSUMER_SECRET` | Yes* | Your Pesapal consumer secret | `sMlGZq...` |
| `PESAPAL_BASE_URL` | Yes* | Pesapal API base URL | `https://cybqa.pesapal.com/pesapalv3` |
| `PESAPAL_IPN_ID` | No | IPN notification ID (auto-registered) | `abc123...` |
| `PESAPAL_MOCK_MODE` | No | Enable mock mode (true/false) | `true` |
| `PUBLIC_BASE_URL` | No | Public URL for callbacks (tunnel) | `https://abc123.ngrok.io` |

*Required only if `PESAPAL_MOCK_MODE` is not set or is `false`

---

## Quick Start Examples

### Example 1: Mock Mode (No Credentials Needed)
```bash
# .env
PESAPAL_MOCK_MODE=true
```
✅ **Pros:** No setup needed, works offline  
❌ **Cons:** Doesn't test real API integration

### Example 2: Sandbox with Tunnel
```bash
# .env
PESAPAL_CONSUMER_KEY=your_sandbox_key
PESAPAL_CONSUMER_SECRET=your_sandbox_secret
PESAPAL_BASE_URL=https://cybqa.pesapal.com/pesapalv3
PESAPAL_MOCK_MODE=false
PUBLIC_BASE_URL=https://abc123.ngrok.io
```
✅ **Pros:** Tests real API integration  
❌ **Cons:** Requires tunnel setup and Pesapal account

### Example 3: Production
```bash
# .env (Production)
PESAPAL_CONSUMER_KEY=your_production_key
PESAPAL_CONSUMER_SECRET=your_production_secret
PESAPAL_BASE_URL=https://pay.pesapal.com/v3  # Production URL
PESAPAL_MOCK_MODE=false
PESAPAL_IPN_ID=your_registered_ipn_id
```
✅ **Pros:** Real payments  
❌ **Cons:** Only use in production environment

---

## Testing Payment Flow

### With Mock Mode:
1. Create a deposit → Get mock redirect URL
2. Visit callback URL → Deposit auto-completes
3. Check deposit status → Should be "COMPLETED"

### With Sandbox:
1. Create a deposit → Get Pesapal sandbox payment URL
2. Complete payment on Pesapal sandbox → Use test card numbers
3. Redirected back → Deposit should complete
4. Check IPN → Should receive notification

---

## Troubleshooting

### "Pesapal consumer key/secret not configured"
- **Solution:** Set `PESAPAL_CONSUMER_KEY` and `PESAPAL_CONSUMER_SECRET` in `.env`
- **Or:** Enable mock mode with `PESAPAL_MOCK_MODE=true`

### "Pesapal IPN not configured"
- **Solution:** Set `PUBLIC_BASE_URL` and let system auto-register IPN
- **Or:** Manually register: `python manage.py register_pesapal_ipn --url "YOUR_URL"`

### "Could not connect to Pesapal API"
- **Check:** Internet connection
- **Check:** `PESAPAL_BASE_URL` is correct
- **Check:** Consumer key/secret are valid
- **Try:** Use mock mode for offline development

### "Invalid credentials"
- **Check:** Using sandbox credentials (not production)
- **Check:** Credentials are copied correctly (no extra spaces)
- **Verify:** Credentials in Pesapal developer dashboard

---

## Security Notes

⚠️ **Never commit real Pesapal credentials to version control!**

- Always use `.env` file (which is gitignored)
- Use sandbox credentials for development
- Use production credentials only in production environment
- Rotate credentials if accidentally exposed

---

## Resources

- **Pesapal Developer Portal:** https://developer.pesapal.com/
- **Pesapal API Documentation:** https://developer.pesapal.com/api3-documentation
- **Sandbox Test Cards:** Check Pesapal documentation for test card numbers

---

**Last Updated:** January 2025
