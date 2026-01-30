# Day 15: Django REST Framework Setup - Documentation

## Overview

Day 15 implements a complete REST API foundation for the PlayyArena platform using Django REST Framework (DRF) with JWT (JSON Web Token) authentication. This provides a secure, scalable API layer for future mobile apps, third-party integrations, and frontend frameworks.

---

## ✅ API Keys Required: **NONE**

**Important:** Day 15 does **NOT** require any external API keys or third-party services. All authentication is handled internally using Django's built-in JWT token system.

### What Uses API Keys (Not Part of Day 15)

The following features in your project **do** require API keys, but they are **separate** from Day 15:

- **Payment Gateways** (Paystack, Flutterwave) - Require secret/public keys
- **Email Services** (SMTP/Gmail) - Require email credentials
- **Future Third-Party Integrations** - May require API keys

**Day 15 itself is completely self-contained and requires zero external API keys.**

---

## What Was Implemented

### 1. Django REST Framework (DRF)
- **Package:** `djangorestframework==3.16.1`
- **Purpose:** Provides REST API framework
- **API Keys Required:** ❌ None

### 2. JWT Authentication
- **Package:** `djangorestframework-simplejwt==5.5.1`
- **Purpose:** Secure token-based authentication
- **API Keys Required:** ❌ None (uses internal Django JWT signing)

### 3. API App Structure
- **Location:** `Arena2/api/`
- **Components:**
  - Serializers (`api/serializers.py`)
  - Views (`api/views.py`)
  - URL routing (`api/urls.py`)
- **API Keys Required:** ❌ None

---

## API Endpoints

All endpoints are available under the `/api/` prefix.

### Authentication Endpoints

#### 1. Get JWT Token
**Endpoint:** `POST /api/auth/token/`

**Purpose:** Obtain access and refresh tokens for authentication.

**Request Body:**
```json
{
  "username": "your_username",
  "password": "your_password"
}
```

**Response:**
```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

**API Keys Required:** ❌ None

**Example (cURL):**
```bash
curl -X POST http://127.0.0.1:8000/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "user123", "password": "password123"}'
```

---

#### 2. Refresh Access Token
**Endpoint:** `POST /api/auth/token/refresh/`

**Purpose:** Get a new access token using a refresh token.

**Request Body:**
```json
{
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

**Response:**
```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

**API Keys Required:** ❌ None

**Example (cURL):**
```bash
curl -X POST http://127.0.0.1:8000/api/auth/token/refresh/ \
  -H "Content-Type: application/json" \
  -d '{"refresh": "your_refresh_token_here"}'
```

---

### Protected Endpoints (Require JWT Authentication)

All protected endpoints require the `Authorization` header with a Bearer token.

**Header Format:**
```
Authorization: Bearer YOUR_ACCESS_TOKEN
```

#### 3. Get Current User
**Endpoint:** `GET /api/me/`

**Purpose:** Retrieve information about the currently authenticated user.

**Authentication:** ✅ Required (JWT Bearer token)

**Response:**
```json
{
  "id": 1,
  "username": "user123",
  "email": "user@example.com"
}
```

**API Keys Required:** ❌ None

**Example (cURL):**
```bash
curl http://127.0.0.1:8000/api/me/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

#### 4. Get User's Matches
**Endpoint:** `GET /api/my-matches/`

**Purpose:** Retrieve all matches where the authenticated user is either the creator or joiner.

**Authentication:** ✅ Required (JWT Bearer token)

**Response:**
```json
[
  {
    "id": 1,
    "game": "FIFA_MOBILE",
    "device": "MOBILE",
    "amount": 50,
    "status": "JOINED",
    "created_at": "2025-01-15T10:30:00Z"
  },
  {
    "id": 2,
    "game": "NBA_2K",
    "device": "PLAYSTATION",
    "amount": 100,
    "status": "COMPLETED",
    "created_at": "2025-01-14T15:20:00Z"
  }
]
```

**API Keys Required:** ❌ None

**Example (cURL):**
```bash
curl http://127.0.0.1:8000/api/my-matches/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

## Configuration

### Settings (`Arena2/core/settings.py`)

#### REST Framework Configuration
```python
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
}
```

**API Keys Required:** ❌ None

#### JWT Token Settings
```python
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'AUTH_HEADER_TYPES': ('Bearer',),
}
```

**API Keys Required:** ❌ None

**Note:** Token lifetimes can be adjusted based on security requirements. No external services are involved.

---

## Security Features

### Token-Based Authentication
- **JWT tokens** are signed using Django's `SECRET_KEY`
- **No external authentication service** required
- **No API keys** needed for token generation or validation

### Token Expiration
- **Access tokens:** Valid for 30 minutes (configurable)
- **Refresh tokens:** Valid for 1 day (configurable)
- Tokens automatically expire and must be refreshed

### Protected Endpoints
- All endpoints except `/api/auth/token/` and `/api/auth/token/refresh/` require authentication
- Unauthenticated requests return `401 Unauthorized`

---

## Installation & Setup

### 1. Install Dependencies
```bash
pip install djangorestframework djangorestframework-simplejwt
```

**API Keys Required:** ❌ None

### 2. Add to INSTALLED_APPS
```python
INSTALLED_APPS = [
    # ... other apps
    'rest_framework',
    'rest_framework_simplejwt',
    'api',
]
```

**API Keys Required:** ❌ None

### 3. Configure URLs
Already configured in `Arena2/core/urls.py`:
```python
path('api/', include('api.urls')),
```

**API Keys Required:** ❌ None

---

## Testing the API

### Using cURL

#### Step 1: Get Token
```bash
curl -X POST http://127.0.0.1:8000/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "your_username", "password": "your_password"}'
```

#### Step 2: Use Token
```bash
curl http://127.0.0.1:8000/api/me/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**API Keys Required:** ❌ None

### Using Python Requests

```python
import requests

# Get token
response = requests.post(
    'http://127.0.0.1:8000/api/auth/token/',
    json={'username': 'your_username', 'password': 'your_password'}
)
tokens = response.json()
access_token = tokens['access']

# Use token
headers = {'Authorization': f'Bearer {access_token}'}
response = requests.get('http://127.0.0.1:8000/api/me/', headers=headers)
user_data = response.json()
```

**API Keys Required:** ❌ None

### Using Postman

1. **Get Token:**
   - Method: `POST`
   - URL: `http://127.0.0.1:8000/api/auth/token/`
   - Body (JSON): `{"username": "user", "password": "pass"}`
   - Copy the `access` token from response

2. **Use Token:**
   - Method: `GET`
   - URL: `http://127.0.0.1:8000/api/me/`
   - Headers: `Authorization: Bearer YOUR_ACCESS_TOKEN`

**API Keys Required:** ❌ None

---

## Error Responses

### 401 Unauthorized
```json
{
  "detail": "Authentication credentials were not provided."
}
```
**Cause:** Missing or invalid JWT token  
**API Keys Required:** ❌ None

### 400 Bad Request
```json
{
  "username": ["This field is required."],
  "password": ["This field is required."]
}
```
**Cause:** Invalid request data  
**API Keys Required:** ❌ None

### 500 Internal Server Error
**Cause:** Server-side error (check logs)  
**API Keys Required:** ❌ None

---

## Future API Integrations (Not Day 15)

The following features **will** require API keys when implemented, but are **not part of Day 15**:

### Payment Processing
- **Paystack:** Requires `PAYSTACK_SECRET_KEY` and `PAYSTACK_PUBLIC_KEY`
- **Flutterwave:** Requires `FLUTTERWAVE_SECRET_KEY` and `FLUTTERWAVE_PUBLIC_KEY`
- **Status:** Already configured in `core/settings.py` (separate from Day 15)

### Email Services
- **SMTP/Gmail:** Requires `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD`
- **Status:** Already configured (separate from Day 15)

### Third-Party Services (Future)
- Social media authentication (OAuth)
- SMS notifications
- Push notifications
- Analytics services

**These are separate features and do not affect Day 15's API setup.**

---

## Summary: API Keys for Day 15

| Component | API Keys Required | Notes |
|-----------|------------------|-------|
| Django REST Framework | ❌ None | Self-contained framework |
| JWT Authentication | ❌ None | Uses Django's SECRET_KEY internally |
| API Endpoints | ❌ None | All endpoints are internal |
| Token Generation | ❌ None | Handled by SimpleJWT library |
| Token Validation | ❌ None | Validated using Django's secret key |
| User Authentication | ❌ None | Uses Django's built-in auth system |

**Total API Keys Required for Day 15: 0**

---

## Verification

To verify Day 15 is working correctly:

1. **Check system:**
   ```bash
   python manage.py check
   ```
   Should return: `System check identified no issues (0 silenced).`

2. **Test token generation:**
   ```bash
   curl -X POST http://127.0.0.1:8000/api/auth/token/ \
     -H "Content-Type: application/json" \
     -d '{"username": "test_user", "password": "test_pass"}'
   ```
   Should return access and refresh tokens.

3. **Test protected endpoint:**
   ```bash
   curl http://127.0.0.1:8000/api/me/ \
     -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
   ```
   Should return user data.

**API Keys Required:** ❌ None for any of these tests.

---

## Files Modified/Created

### Created Files
- `Arena2/api/__init__.py`
- `Arena2/api/apps.py`
- `Arena2/api/serializers.py`
- `Arena2/api/views.py`
- `Arena2/api/urls.py`
- `Arena2/api/admin.py`
- `Arena2/api/models.py`
- `Arena2/api/tests.py`

### Modified Files
- `Arena2/core/settings.py` (added DRF config, JWT config, api app)
- `Arena2/core/urls.py` (added API routes)
- `Arena2/requirements.txt` (added DRF packages)

**API Keys Required:** ❌ None for any file modifications.

---

## Support

For issues or questions about Day 15:

1. **Check Django logs:** `python manage.py runserver` shows errors
2. **Verify settings:** Ensure `api` is in `INSTALLED_APPS`
3. **Check URLs:** Verify `path('api/', include('api.urls'))` is in `core/urls.py`
4. **Test authentication:** Use the examples above

**Remember:** Day 15 requires **zero API keys**. If you're being asked for API keys, you're likely working on a different feature (payment gateways, email, etc.).

---

## Conclusion

Day 15 provides a complete, self-contained REST API foundation that requires **no external API keys or services**. All authentication is handled internally using Django's JWT implementation. This makes it easy to deploy and test without any external dependencies.

**API Keys Required: 0** ✅

