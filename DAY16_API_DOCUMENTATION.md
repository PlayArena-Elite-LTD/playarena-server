# Day 16: User & Authentication API - Documentation

## Overview

Day 16 implements comprehensive User and Authentication API endpoints for the PlayyArena platform. This provides complete user management, authentication, and profile handling capabilities through a REST API.

---

## ✅ API Keys Required: **NONE**

**Important:** Day 16 does **NOT** require any external API keys or third-party services. All functionality is handled internally using Django's built-in systems.

### What Uses API Keys (Not Part of Day 16)

The following features in your project **do** require API keys, but they are **separate** from Day 16:

- **Payment Gateways** (Paystack, Flutterwave) - Require secret/public keys
- **Email Services** (SMTP/Gmail) - Require email credentials
- **Future Third-Party Integrations** - May require API keys

**Day 16 itself is completely self-contained and requires zero external API keys.**

---

## What Was Implemented

### 1. User Registration API
- **Endpoint:** `POST /api/auth/register/`
- **Purpose:** Register new users and get JWT tokens
- **API Keys Required:** ❌ None

### 2. Authentication API
- **Endpoints:** Login, token refresh, password change, password reset
- **Purpose:** Complete authentication flow
- **API Keys Required:** ❌ None (uses Django's JWT system)

### 3. User Management API
- **Endpoints:** Get/update current user, list users, get user by ID
- **Purpose:** User profile management
- **API Keys Required:** ❌ None

### 4. Profile Management API
- **Endpoint:** Get/update user profile (first_name, last_name)
- **Purpose:** Profile data management
- **API Keys Required:** ❌ None

---

## API Endpoints

All endpoints are available under the `/api/` prefix.

### Authentication Endpoints

#### 1. Register User
**Endpoint:** `POST /api/auth/register/`

**Purpose:** Register a new user and receive JWT tokens.

**Request Body:**
```json
{
  "username": "newuser",
  "email": "user@example.com",
  "password": "securepassword123",
  "password_confirm": "securepassword123"
}
```

**Response:**
```json
{
  "user": {
    "id": 1,
    "username": "newuser",
    "email": "user@example.com",
    "date_joined": "2025-01-30T10:00:00Z",
    "is_support_staff": false,
    "is_active": true,
    "profile": {
      "first_name": "",
      "last_name": ""
    }
  },
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

**API Keys Required:** ❌ None

**Example (cURL):**
```bash
curl -X POST http://127.0.0.1:8000/api/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "newuser",
    "email": "user@example.com",
    "password": "securepass123",
    "password_confirm": "securepass123"
  }'
```

---

#### 2. Get JWT Token (Login)
**Endpoint:** `POST /api/auth/token/`

**Purpose:** Obtain access and refresh tokens for existing users.

**Request Body:**
```json
{
  "username": "existinguser",
  "password": "password123"
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
  -d '{"username": "user123", "password": "pass123"}'
```

---

#### 3. Refresh Access Token
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

---

#### 4. Change Password
**Endpoint:** `POST /api/auth/change-password/`

**Purpose:** Change user password. Requires authentication.

**Request Body:**
```json
{
  "old_password": "oldpass123",
  "new_password": "newpass123",
  "new_password_confirm": "newpass123"
}
```

**Response:**
```json
{
  "message": "Password changed successfully"
}
```

**Authentication:** ✅ Required (JWT Bearer token)

**API Keys Required:** ❌ None

**Example (cURL):**
```bash
curl -X POST http://127.0.0.1:8000/api/auth/change-password/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "old_password": "oldpass",
    "new_password": "newpass123",
    "new_password_confirm": "newpass123"
  }'
```

---

#### 5. Request Password Reset
**Endpoint:** `POST /api/auth/password-reset/`

**Purpose:** Request password reset. Basic implementation (email service can be added later).

**Request Body:**
```json
{
  "email": "user@example.com"
}
```

**Response:**
```json
{
  "message": "If an account exists with this email, a password reset link has been sent."
}
```

**API Keys Required:** ❌ None

**Note:** This is a basic implementation. For production, you can integrate with Django's password reset system or your email service (which would require email credentials, but that's separate from Day 16).

**Example (cURL):**
```bash
curl -X POST http://127.0.0.1:8000/api/auth/password-reset/ \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com"}'
```

---

### User Endpoints

#### 6. Get Current User
**Endpoint:** `GET /api/me/`

**Purpose:** Retrieve information about the currently authenticated user.

**Authentication:** ✅ Required (JWT Bearer token)

**Response:**
```json
{
  "id": 1,
  "username": "user123",
  "email": "user@example.com",
  "date_joined": "2025-01-30T10:00:00Z",
  "is_support_staff": false,
  "is_active": true,
  "profile": {
    "first_name": "John",
    "last_name": "Doe"
  }
}
```

**API Keys Required:** ❌ None

**Example (cURL):**
```bash
curl http://127.0.0.1:8000/api/me/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

#### 7. Update Current User
**Endpoint:** `PUT /api/me/` or `PATCH /api/me/`

**Purpose:** Update current user information (username, email, first_name, last_name).

**Authentication:** ✅ Required (JWT Bearer token)

**Request Body:**
```json
{
  "username": "updatedusername",
  "email": "updated@example.com",
  "first_name": "Jane",
  "last_name": "Smith"
}
```

**Response:**
```json
{
  "id": 1,
  "username": "updatedusername",
  "email": "updated@example.com",
  "date_joined": "2025-01-30T10:00:00Z",
  "is_support_staff": false,
  "is_active": true,
  "profile": {
    "first_name": "Jane",
    "last_name": "Smith"
  }
}
```

**API Keys Required:** ❌ None

**Example (cURL):**
```bash
curl -X PATCH http://127.0.0.1:8000/api/me/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "first_name": "Jane",
    "last_name": "Smith"
  }'
```

---

#### 8. List All Users
**Endpoint:** `GET /api/users/`

**Purpose:** List all users. Admin and staff only.

**Authentication:** ✅ Required (JWT Bearer token)
**Permission:** ✅ Admin/Staff only

**Response:**
```json
[
  {
    "id": 1,
    "username": "user1",
    "date_joined": "2025-01-30T10:00:00Z",
    "profile": {
      "first_name": "John",
      "last_name": "Doe"
    }
  },
  {
    "id": 2,
    "username": "user2",
    "date_joined": "2025-01-29T15:30:00Z",
    "profile": {
      "first_name": "Jane",
      "last_name": "Smith"
    }
  }
]
```

**Query Parameters:**
- `username` - Filter by username (partial match): `?username=search`

**API Keys Required:** ❌ None

**Example (cURL):**
```bash
curl http://127.0.0.1:8000/api/users/ \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN"
```

---

#### 9. Get User by ID
**Endpoint:** `GET /api/users/{id}/`

**Purpose:** Retrieve public profile information for a specific user.

**Authentication:** ❌ Not required (public endpoint)

**Response:**
```json
{
  "id": 1,
  "username": "user123",
  "date_joined": "2025-01-30T10:00:00Z",
  "profile": {
    "first_name": "John",
    "last_name": "Doe"
  }
}
```

**Note:** This endpoint uses `PublicUserSerializer` which excludes sensitive data like email.

**API Keys Required:** ❌ None

**Example (cURL):**
```bash
curl http://127.0.0.1:8000/api/users/1/
```

---

### Profile Endpoints

#### 10. Get Current User's Profile
**Endpoint:** `GET /api/me/profile/`

**Purpose:** Retrieve current user's profile (first_name, last_name).

**Authentication:** ✅ Required (JWT Bearer token)

**Response:**
```json
{
  "first_name": "John",
  "last_name": "Doe"
}
```

**API Keys Required:** ❌ None

**Example (cURL):**
```bash
curl http://127.0.0.1:8000/api/me/profile/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

#### 11. Update Current User's Profile
**Endpoint:** `PUT /api/me/profile/` or `PATCH /api/me/profile/`

**Purpose:** Update current user's profile (first_name, last_name).

**Authentication:** ✅ Required (JWT Bearer token)

**Request Body:**
```json
{
  "first_name": "Jane",
  "last_name": "Smith"
}
```

**Response:**
```json
{
  "first_name": "Jane",
  "last_name": "Smith"
}
```

**API Keys Required:** ❌ None

**Example (cURL):**
```bash
curl -X PATCH http://127.0.0.1:8000/api/me/profile/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "first_name": "Jane",
    "last_name": "Smith"
  }'
```

**Note:** Profile is automatically created if it doesn't exist.

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
- Most endpoints require authentication (JWT Bearer token)
- Admin-only endpoints check for admin/staff permissions
- Public endpoints (user detail, registration) don't require authentication

### Password Security
- Passwords are hashed using Django's password hashing
- Password strength validation (Django validators)
- Old password verification for password changes
- No API keys required for password management

---

## Validation Features

### User Registration
- Email uniqueness check
- Username uniqueness check
- Password strength validation
- Password confirmation matching

### User Updates
- Email uniqueness (excluding current user)
- Username uniqueness (excluding current user)
- Profile field validation

### Password Changes
- Old password verification
- New password strength validation
- Password confirmation matching

**All validation is handled internally - no API keys required.**

---

## Error Responses

### 400 Bad Request
```json
{
  "username": ["A user with this username already exists."],
  "email": ["A user with this email already exists."]
}
```
**Cause:** Validation errors  
**API Keys Required:** ❌ None

### 401 Unauthorized
```json
{
  "detail": "Authentication credentials were not provided."
}
```
**Cause:** Missing or invalid JWT token  
**API Keys Required:** ❌ None

### 403 Forbidden
```json
{
  "detail": "You do not have permission to perform this action."
}
```
**Cause:** Insufficient permissions (e.g., non-admin accessing admin endpoint)  
**API Keys Required:** ❌ None

### 404 Not Found
```json
{
  "detail": "Not found."
}
```
**Cause:** Resource doesn't exist  
**API Keys Required:** ❌ None

---

## Complete API Endpoint Summary

| Endpoint | Method | Auth Required | Admin Only | API Keys |
|----------|--------|---------------|------------|----------|
| `/api/auth/register/` | POST | ❌ No | ❌ No | ❌ None |
| `/api/auth/token/` | POST | ❌ No | ❌ No | ❌ None |
| `/api/auth/token/refresh/` | POST | ❌ No | ❌ No | ❌ None |
| `/api/auth/change-password/` | POST | ✅ Yes | ❌ No | ❌ None |
| `/api/auth/password-reset/` | POST | ❌ No | ❌ No | ❌ None |
| `/api/me/` | GET | ✅ Yes | ❌ No | ❌ None |
| `/api/me/` | PUT/PATCH | ✅ Yes | ❌ No | ❌ None |
| `/api/users/` | GET | ✅ Yes | ✅ Yes | ❌ None |
| `/api/users/{id}/` | GET | ❌ No | ❌ No | ❌ None |
| `/api/me/profile/` | GET | ✅ Yes | ❌ No | ❌ None |
| `/api/me/profile/` | PUT/PATCH | ✅ Yes | ❌ No | ❌ None |

**Total API Keys Required for Day 16: 0**

---

## Future Enhancements (Not Part of Day 16)

The following features **will** require API keys when implemented, but are **not part of Day 16**:

### Email Service Integration
- **Password Reset Emails:** Can integrate with SMTP/Gmail (requires email credentials)
- **Email Verification:** Can add email verification on registration
- **Status:** Basic password reset endpoint exists; email sending can be added later

### Third-Party Services (Future)
- Social media authentication (OAuth - Facebook, Google, etc.)
- SMS notifications
- Push notifications
- Analytics services

**These are separate features and do not affect Day 16's API setup.**

---

## Testing the API

### Using cURL

#### 1. Register User
```bash
curl -X POST http://127.0.0.1:8000/api/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "email": "test@example.com",
    "password": "testpass123",
    "password_confirm": "testpass123"
  }'
```

#### 2. Get Token
```bash
curl -X POST http://127.0.0.1:8000/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser", "password": "testpass123"}'
```

#### 3. Get Current User
```bash
curl http://127.0.0.1:8000/api/me/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### 4. Update Profile
```bash
curl -X PATCH http://127.0.0.1:8000/api/me/profile/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"first_name": "John", "last_name": "Doe"}'
```

**API Keys Required:** ❌ None for any of these operations

---

## Files Modified/Created

### Created Files
- All endpoints are in existing `api` app (created in Day 15)

### Modified Files
- `Arena2/api/serializers.py` - Added User, Profile, Registration, Update, Password serializers
- `Arena2/api/views.py` - Added all authentication and user management views
- `Arena2/api/urls.py` - Added all API routes

**API Keys Required:** ❌ None for any file modifications

---

## Summary: API Keys for Day 16

| Component | API Keys Required | Notes |
|-----------|------------------|-------|
| User Registration | ❌ None | Uses Django's user model |
| JWT Authentication | ❌ None | Uses Django's SECRET_KEY internally |
| Password Management | ❌ None | Uses Django's password hashing |
| User Endpoints | ❌ None | All endpoints are internal |
| Profile Endpoints | ❌ None | Uses Django's Profile model |
| Token Generation | ❌ None | Handled by SimpleJWT library |
| Token Validation | ❌ None | Validated using Django's secret key |
| User Validation | ❌ None | Uses Django's validation system |

**Total API Keys Required for Day 16: 0**

---

## Verification

To verify Day 16 is working correctly:

1. **Check system:**
   ```bash
   python manage.py check
   ```
   Should return: `System check identified no issues (0 silenced).`

2. **Test registration:**
   ```bash
   curl -X POST http://127.0.0.1:8000/api/auth/register/ \
     -H "Content-Type: application/json" \
     -d '{"username": "test", "email": "test@example.com", "password": "testpass123", "password_confirm": "testpass123"}'
   ```
   Should return user data + tokens.

3. **Test get current user:**
   ```bash
   curl http://127.0.0.1:8000/api/me/ \
     -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
   ```
   Should return user data.

4. **Test update profile:**
   ```bash
   curl -X PATCH http://127.0.0.1:8000/api/me/profile/ \
     -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"first_name": "Test", "last_name": "User"}'
   ```
   Should return updated profile.

**API Keys Required:** ❌ None for any of these tests.

---

## Support

For issues or questions about Day 16:

1. **Check Django logs:** `python manage.py runserver` shows errors
2. **Verify settings:** Ensure `api` is in `INSTALLED_APPS`
3. **Check URLs:** Verify API routes are in `core/urls.py`
4. **Test authentication:** Use the examples above

**Remember:** Day 16 requires **zero API keys**. If you're being asked for API keys, you're likely working on a different feature (payment gateways, email, etc.).

---

## Conclusion

Day 16 provides a complete, self-contained User & Authentication API that requires **no external API keys or services**. All functionality is handled internally using Django's built-in systems and the JWT implementation from Day 15. This makes it easy to deploy and test without any external dependencies.

**API Keys Required: 0** ✅

---

## Quick Reference

### Authentication Flow
1. **Register:** `POST /api/auth/register/` → Get tokens
2. **Login:** `POST /api/auth/token/` → Get tokens
3. **Use Token:** Include `Authorization: Bearer TOKEN` header
4. **Refresh:** `POST /api/auth/token/refresh/` → Get new access token

### User Management Flow
1. **Get Profile:** `GET /api/me/` → Full user data
2. **Update Profile:** `PATCH /api/me/` → Update user info
3. **Get Profile Only:** `GET /api/me/profile/` → Profile data only
4. **Update Profile Only:** `PATCH /api/me/profile/` → Update profile

**All operations require zero API keys.**

