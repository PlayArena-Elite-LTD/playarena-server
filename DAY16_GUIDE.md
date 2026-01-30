# Day 16: User & Authentication API - Step-by-Step Guide

## Overview

Day 16 builds on Day 15's foundation to create comprehensive User, Authentication, and Profile API endpoints. This will enable mobile apps and third-party integrations to manage users, authenticate, and handle profiles.

---

## Prerequisites

- ✅ Day 15 completed (DRF + JWT working)
- ✅ API app created (`Arena2/api/`)
- ✅ JWT authentication functional

---

## Step-by-Step Implementation

### **Step 1: Enhance User Serializer**

**Goal:** Expand `UserSerializer` to include more fields and add a `ProfileSerializer`.

**File:** `Arena2/api/serializers.py`

**Actions:**
1. Update `UserSerializer` to include:
   - `date_joined`
   - `is_support_staff`
   - `is_active`
   - Nested profile data (optional)
2. Create `ProfileSerializer` for profile fields
3. Create `UserRegistrationSerializer` for registration (password handling)
4. Create `UserUpdateSerializer` for user updates

**Expected Result:**
- Complete user data serialization
- Profile data included
- Registration-ready serializer

---

### **Step 2: Create Authentication API Endpoints**

**Goal:** Add registration, password change, and password reset endpoints.

**File:** `Arena2/api/views.py`

**Actions:**
1. Create `UserRegistrationView` (POST `/api/auth/register/`)
   - Accept username, email, password
   - Create new user
   - Return JWT tokens
2. Create `ChangePasswordView` (POST `/api/auth/change-password/`)
   - Accept old_password, new_password
   - Update user password
   - Require authentication
3. Create `PasswordResetRequestView` (POST `/api/auth/password-reset/`)
   - Accept email
   - Send reset link (optional for now, can use email service later)
4. Keep existing JWT token endpoints from Day 15

**Expected Result:**
- Complete authentication flow (register, login, password management)
- All endpoints return proper JSON responses

---

### **Step 3: Create User API Endpoints**

**Goal:** Add endpoints for user management (list, retrieve, update, delete).

**File:** `Arena2/api/views.py`

**Actions:**
1. Enhance `MeView` (already exists, may need updates)
   - GET `/api/me/` - Get current user
   - PUT/PATCH `/api/me/` - Update current user
2. Create `UserListView` (GET `/api/users/`)
   - List all users (admin/staff only)
   - Pagination support
3. Create `UserDetailView` (GET `/api/users/{id}/`)
   - Retrieve specific user
   - Public profile info only
4. Create `UserUpdateView` (PUT/PATCH `/api/me/`)
   - Update own profile
   - Require authentication

**Expected Result:**
- Full CRUD operations for users
- Proper permissions (users can only edit themselves)
- Admin can view all users

---

### **Step 4: Create Profile API Endpoints**

**Goal:** Add endpoints for profile management (first_name, last_name).

**File:** `Arena2/api/views.py` and `Arena2/api/serializers.py`

**Actions:**
1. Create `ProfileSerializer` (in serializers.py)
   - Include: first_name, last_name
   - Nested in UserSerializer or separate
2. Create `ProfileView` (GET/PUT/PATCH `/api/me/profile/`)
   - Get current user's profile
   - Update profile fields
   - Require authentication

**Expected Result:**
- Profile can be retrieved and updated via API
- Profile data included in user responses

---

### **Step 5: Update API URLs**

**Goal:** Wire up all new endpoints.

**File:** `Arena2/api/urls.py`

**Actions:**
1. Add registration endpoint
2. Add password change endpoint
3. Add password reset endpoint
4. Add user list/detail endpoints
5. Add profile endpoint
6. Keep existing JWT endpoints from Day 15

**Expected Result:**
- All endpoints accessible under `/api/`
- Clean URL structure

---

### **Step 6: Add Permissions & Validation**

**Goal:** Ensure proper security and validation.

**File:** `Arena2/api/views.py` and `Arena2/api/serializers.py`

**Actions:**
1. Add permission classes:
   - `IsAuthenticated` for protected endpoints
   - `IsAdminUser` for admin-only endpoints
2. Add validation:
   - Email uniqueness
   - Password strength
   - Username uniqueness
3. Add error handling:
   - Proper error responses
   - Validation error messages

**Expected Result:**
- Secure endpoints
- Clear error messages
- Proper validation

---

### **Step 7: Test All Endpoints**

**Goal:** Verify everything works correctly.

**Actions:**
1. Test registration:
   ```bash
   POST /api/auth/register/
   ```
2. Test login (existing):
   ```bash
   POST /api/auth/token/
   ```
3. Test get current user:
   ```bash
   GET /api/me/
   ```
4. Test update profile:
   ```bash
   PATCH /api/me/profile/
   ```
5. Test change password:
   ```bash
   POST /api/auth/change-password/
   ```

**Expected Result:**
- All endpoints return correct responses
- Authentication works
- Updates persist

---

## Detailed Implementation Checklist

### ✅ **Step 1: Serializers** (`api/serializers.py`)

- [ ] Update `UserSerializer` with more fields
- [ ] Create `ProfileSerializer`
- [ ] Create `UserRegistrationSerializer` (password write-only)
- [ ] Create `UserUpdateSerializer` (exclude password)
- [ ] Create `ChangePasswordSerializer`
- [ ] Add validation methods

### ✅ **Step 2: Authentication Views** (`api/views.py`)

- [ ] `UserRegistrationView` - POST `/api/auth/register/`
- [ ] `ChangePasswordView` - POST `/api/auth/change-password/`
- [ ] `PasswordResetRequestView` - POST `/api/auth/password-reset/` (optional)
- [ ] Keep existing `TokenObtainPairView` and `TokenRefreshView`

### ✅ **Step 3: User Views** (`api/views.py`)

- [ ] Enhance `MeView` - GET/PUT/PATCH `/api/me/`
- [ ] `UserListView` - GET `/api/users/` (admin only)
- [ ] `UserDetailView` - GET `/api/users/{id}/` (public profile)

### ✅ **Step 4: Profile Views** (`api/views.py`)

- [ ] `ProfileView` - GET/PUT/PATCH `/api/me/profile/`

### ✅ **Step 5: URLs** (`api/urls.py`)

- [ ] Add registration route
- [ ] Add password change route
- [ ] Add password reset route (optional)
- [ ] Add user list route
- [ ] Add user detail route
- [ ] Add profile route
- [ ] Keep existing JWT routes

### ✅ **Step 6: Permissions & Security**

- [ ] Add `IsAuthenticated` to protected endpoints
- [ ] Add `IsAdminUser` to admin endpoints
- [ ] Add validation in serializers
- [ ] Test unauthorized access (should return 401/403)

### ✅ **Step 7: Testing**

- [ ] Test registration flow
- [ ] Test login flow
- [ ] Test get current user
- [ ] Test update user
- [ ] Test update profile
- [ ] Test change password
- [ ] Test error cases (invalid data, unauthorized)

---

## API Endpoints Summary

### **Authentication Endpoints**

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/api/auth/register/` | Register new user | ❌ No |
| POST | `/api/auth/token/` | Get JWT tokens | ❌ No |
| POST | `/api/auth/token/refresh/` | Refresh access token | ❌ No |
| POST | `/api/auth/change-password/` | Change password | ✅ Yes |
| POST | `/api/auth/password-reset/` | Request password reset | ❌ No (optional) |

### **User Endpoints**

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/me/` | Get current user | ✅ Yes |
| PUT/PATCH | `/api/me/` | Update current user | ✅ Yes |
| GET | `/api/users/` | List all users | ✅ Yes (Admin) |
| GET | `/api/users/{id}/` | Get user by ID | ❌ No (public profile) |

### **Profile Endpoints**

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/me/profile/` | Get current profile | ✅ Yes |
| PUT/PATCH | `/api/me/profile/` | Update current profile | ✅ Yes |

---

## Example Request/Response

### **Registration**
```json
POST /api/auth/register/
{
  "username": "newuser",
  "email": "newuser@example.com",
  "password": "securepassword123"
}

Response:
{
  "user": {
    "id": 1,
    "username": "newuser",
    "email": "newuser@example.com"
  },
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

### **Update Profile**
```json
PATCH /api/me/profile/
Authorization: Bearer YOUR_TOKEN
{
  "first_name": "John",
  "last_name": "Doe"
}

Response:
{
  "first_name": "John",
  "last_name": "Doe"
}
```

### **Change Password**
```json
POST /api/auth/change-password/
Authorization: Bearer YOUR_TOKEN
{
  "old_password": "oldpass123",
  "new_password": "newpass123"
}

Response:
{
  "message": "Password changed successfully"
}
```

---

## Testing Commands

### **1. Register User**
```bash
curl -X POST http://127.0.0.1:8000/api/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser", "email": "test@example.com", "password": "testpass123"}'
```

### **2. Get Current User**
```bash
curl http://127.0.0.1:8000/api/me/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### **3. Update Profile**
```bash
curl -X PATCH http://127.0.0.1:8000/api/me/profile/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"first_name": "John", "last_name": "Doe"}'
```

### **4. Change Password**
```bash
curl -X POST http://127.0.0.1:8000/api/auth/change-password/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"old_password": "oldpass", "new_password": "newpass123"}'
```

---

## Success Criteria

Day 16 is complete when:

- ✅ Users can register via API
- ✅ Users can authenticate and get JWT tokens
- ✅ Users can retrieve and update their own profile
- ✅ Users can change their password
- ✅ Admin can list all users
- ✅ All endpoints return proper JSON responses
- ✅ All endpoints have proper permissions
- ✅ Error handling works correctly

---

## Next Steps After Day 16

- Day 17: Match API endpoints
- Day 18: Wallet API endpoints
- Day 19: Evidence API endpoints
- Day 20: Dispute API endpoints

---

## Notes

- **Password Reset:** Can be implemented with email service (already configured in settings)
- **Email Verification:** Can be added later if needed
- **Profile Picture:** Can be added to Profile model and serializer later
- **Rate Limiting:** Already configured from Day 2, applies to these endpoints

---

## Estimated Time

- **Step 1 (Serializers):** 1-2 hours
- **Step 2 (Auth Views):** 2-3 hours
- **Step 3 (User Views):** 1-2 hours
- **Step 4 (Profile Views):** 1 hour
- **Step 5 (URLs):** 30 minutes
- **Step 6 (Permissions):** 1 hour
- **Step 7 (Testing):** 1-2 hours

**Total:** 8-12 hours

