# Day 19 & Day 20: API Implementation & Documentation

## Overview

This document provides comprehensive documentation for **Day 19: Dispute & Messaging API** and **Day 20: API Documentation & Testing**. These two days focused on implementing REST API endpoints for disputes, messaging, and notifications, followed by comprehensive documentation, testing, and developer resources.

---

## Table of Contents

1. [Day 19: Dispute & Messaging API](#day-19-dispute--messaging-api)
   - [Overview](#overview-1)
   - [APIs Implemented](#apis-implemented)
   - [Endpoints](#endpoints)
   - [Usage Examples](#usage-examples)
2. [Day 20: API Documentation & Testing](#day-20-api-documentation--testing)
   - [Overview](#overview-2)
   - [Components Implemented](#components-implemented)
   - [Documentation Resources](#documentation-resources)
   - [Testing Resources](#testing-resources)
3. [Complete API Reference](#complete-api-reference)
4. [Quick Start Guide](#quick-start-guide)
5. [Troubleshooting](#troubleshooting)

---

## Day 19: Dispute & Messaging API

### Overview

Day 19 implemented REST API endpoints for three core features:
1. **Dispute Management API** - List, view, and resolve disputes
2. **Messaging API** - Send messages, view conversations, manage messages
3. **Notification API** - List notifications, mark as read, get unread count

All endpoints use JWT authentication and include proper permissions for different user roles.

### APIs Implemented

#### 1. Dispute API

**Purpose:** Manage disputes between match participants

**Key Features:**
- Support staff can view all disputes
- Regular users can only view disputes for their own matches
- Support staff can resolve disputes
- Status filtering (OPEN, PENDING, RESOLVED)
- Includes match information in responses

**Endpoints:**
- `GET /api/disputes/` - List disputes (with optional status filter)
- `GET /api/disputes/{id}/` - Get dispute detail
- `POST /api/disputes/{id}/resolve/` - Resolve dispute (staff only)

**Permissions:**
- List/Detail: Authenticated users (filtered by role)
- Resolve: Support staff only

#### 2. Messaging API

**Purpose:** Enable user-to-user messaging

**Key Features:**
- Send messages to other users
- List all messages (sent and received)
- View conversations with specific users
- List all conversations with unread counts
- Automatic read marking when viewing conversations
- Cannot message yourself

**Endpoints:**
- `GET /api/messages/` - List all messages
- `POST /api/messages/` - Send a new message
- `GET /api/messages/{id}/` - Get message detail
- `GET /api/messages/conversations/` - List all conversations
- `GET /api/messages/conversation/{user_id}/` - Get conversation with a user

**Permissions:**
- All endpoints: Authenticated users only
- Users can only access their own messages

#### 3. Notification API

**Purpose:** Manage user notifications

**Key Features:**
- List all notifications for current user
- Get notification detail
- Get unread notification count
- Mark individual notifications as read
- Mark all notifications as read
- Automatic notification creation for messages and dispute resolutions

**Endpoints:**
- `GET /api/notifications/` - List all notifications
- `GET /api/notifications/{id}/` - Get notification detail
- `GET /api/notifications/unread-count/` - Get unread count
- `POST /api/notifications/{id}/mark-read/` - Mark notification as read
- `POST /api/notifications/mark-all-read/` - Mark all notifications as read

**Permissions:**
- All endpoints: Authenticated users only
- Users can only access their own notifications

### Endpoints

#### Dispute Endpoints

##### List Disputes
```http
GET /api/disputes/
Authorization: Bearer {access_token}
```

**Query Parameters:**
- `status` (optional): Filter by status (OPEN, PENDING, RESOLVED)

**Response:**
```json
[
  {
    "id": 1,
    "match_id": 5,
    "match_game": "FIFA Mobile",
    "match_amount": "50.00",
    "match_status": "DISPUTED",
    "status": "OPEN",
    "created_at": "2026-01-31T10:00:00Z",
    "assigned_to_username": null,
    "creator_username": "user1",
    "joiner_username": "user2"
  }
]
```

##### Get Dispute Detail
```http
GET /api/disputes/{id}/
Authorization: Bearer {access_token}
```

##### Resolve Dispute (Staff Only)
```http
POST /api/disputes/{id}/resolve/
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "status": "RESOLVED",
  "resolution_notes": "Dispute resolved in favor of creator."
}
```

#### Messaging Endpoints

##### Send Message
```http
POST /api/messages/
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "receiver": 2,
  "message": "Hello! How are you?"
}
```

##### List Conversations
```http
GET /api/messages/conversations/
Authorization: Bearer {access_token}
```

**Response:**
```json
[
  {
    "user_id": 2,
    "username": "user2",
    "latest_message": {
      "id": 5,
      "message": "Hello!",
      "created_at": "2026-01-31T10:00:00Z"
    },
    "unread_count": 2
  }
]
```

##### Get Conversation
```http
GET /api/messages/conversation/{user_id}/
Authorization: Bearer {access_token}
```

#### Notification Endpoints

##### Get Unread Count
```http
GET /api/notifications/unread-count/
Authorization: Bearer {access_token}
```

**Response:**
```json
{
  "unread_count": 5
}
```

##### Mark All as Read
```http
POST /api/notifications/mark-all-read/
Authorization: Bearer {access_token}
```

### Usage Examples

See `API_USAGE_EXAMPLES.md` for complete code examples in Python, JavaScript, and cURL.

---

## Day 20: API Documentation & Testing

### Overview

Day 20 focused on creating comprehensive documentation, testing infrastructure, and developer resources for the API:

1. **Swagger/OpenAPI Documentation** - Interactive API documentation
2. **API Test Suite** - Automated tests for all endpoints
3. **Postman Collection** - Manual testing collection
4. **Rate Limiting** - API protection
5. **Usage Examples** - Code examples for developers

### Components Implemented

#### 1. Swagger/OpenAPI Documentation

**Technology:** drf-spectacular

**Features:**
- Interactive API documentation
- Try-it-out functionality
- Request/response examples
- Authentication testing
- Schema export

**Access Points:**
- Swagger UI: `http://localhost:8000/api/schema/swagger-ui/`
- ReDoc: `http://localhost:8000/api/schema/redoc/`
- OpenAPI Schema: `http://localhost:8000/api/schema/`

**Configuration:**
- Title: "PlayyArena API"
- Version: "1.0.0"
- Schema path prefix: "/api/"
- JWT authentication whitelisted

#### 2. API Test Suite

**Location:** `api/tests.py`

**Test Coverage:**
- **Dispute API Tests:** 8 tests
  - List disputes (regular user, staff)
  - Status filtering
  - Get dispute detail
  - Resolve dispute (permissions)
  - Unauthenticated access
  
- **Message API Tests:** 10 tests
  - Send message
  - Notification creation
  - Self-messaging prevention
  - List messages
  - Conversations
  - Read marking
  
- **Notification API Tests:** 10 tests
  - List notifications
  - Get detail
  - Unread count
  - Mark as read
  - Mark all read
  - Permissions

**Total Tests:** 28 automated tests

**Run Tests:**
```bash
python manage.py test api.tests
```

#### 3. Postman Collection

**Location:** `postman/PlayyArena_API.postman_collection.json`

**Features:**
- 24 API endpoints organized in 6 folders
- Auto token extraction (JWT tokens saved automatically)
- Collection variables (base_url, access_token, refresh_token)
- Request descriptions and examples
- Authorization headers pre-configured

**Folders:**
- Authentication (5 requests)
- Users (5 requests)
- Matches (1 request)
- Disputes (3 requests)
- Messages (5 requests)
- Notifications (5 requests)

**Import Instructions:**
1. Open Postman
2. Click "Import"
3. Select `postman/PlayyArena_API.postman_collection.json`
4. Collection imported with all requests

#### 4. Rate Limiting

**Configuration:** `core/settings.py`

**Rate Limits:**
- Anonymous users: 100 requests/hour
- Authenticated users: 1000 requests/hour
- Authentication endpoints: 10 requests/minute

**Implementation:**
- Uses DRF's built-in throttling
- `AnonRateThrottle` for anonymous users
- `UserRateThrottle` for authenticated users
- Custom throttle scope for auth endpoints

**Response Headers:**
- `X-RateLimit-Limit`: Maximum requests allowed
- `X-RateLimit-Remaining`: Remaining requests
- `X-RateLimit-Reset`: Reset time (Unix timestamp)

#### 5. API Usage Examples

**Location:** `API_USAGE_EXAMPLES.md`

**Contents:**
- Python examples (27 functions)
- JavaScript examples (14 functions)
- cURL examples (22 commands)
- Error handling patterns
- Best practices guide

**Sections:**
- Authentication examples
- User management examples
- Match examples
- Dispute examples
- Messaging examples
- Notification examples
- Error handling
- Best practices

### Documentation Resources

#### Interactive Documentation
- **Swagger UI:** `http://localhost:8000/api/schema/swagger-ui/`
  - Try endpoints directly
  - View request/response schemas
  - Test authentication
  
- **ReDoc:** `http://localhost:8000/api/schema/redoc/`
  - Clean, readable documentation
  - Search functionality
  - Schema details

#### Code Examples
- **API Usage Examples:** `API_USAGE_EXAMPLES.md`
  - Complete code examples
  - Multiple languages
  - Error handling
  - Best practices

#### Testing Resources
- **Postman Collection:** `postman/PlayyArena_API.postman_collection.json`
  - Import into Postman
  - Test all endpoints
  - Auto token management

### Testing Resources

#### Automated Tests
- **Test Suite:** `api/tests.py`
- **Run Tests:** `python manage.py test api.tests`
- **Coverage:** 28 tests covering all endpoints

#### Manual Testing
- **Postman Collection:** Import and test manually
- **Swagger UI:** Use "Try it out" feature
- **cURL Examples:** Copy from `API_USAGE_EXAMPLES.md`

---

## Complete API Reference

### Authentication Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/api/auth/register/` | Register new user | No |
| POST | `/api/auth/token/` | Get JWT tokens | No |
| POST | `/api/auth/token/refresh/` | Refresh access token | No |
| POST | `/api/auth/change-password/` | Change password | Yes |
| POST | `/api/auth/password-reset/` | Request password reset | No |

### User Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/me/` | Get current user | Yes |
| GET | `/api/me/profile/` | Get my profile | Yes |
| PUT | `/api/me/profile/` | Update my profile | Yes |
| GET | `/api/users/` | List users | Yes |
| GET | `/api/users/{id}/` | Get user detail | Yes |

### Match Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/my-matches/` | Get my matches | Yes |

### Dispute Endpoints

| Method | Endpoint | Description | Auth Required | Staff Only |
|--------|----------|-------------|---------------|------------|
| GET | `/api/disputes/` | List disputes | Yes | No |
| GET | `/api/disputes/{id}/` | Get dispute detail | Yes | No |
| POST | `/api/disputes/{id}/resolve/` | Resolve dispute | Yes | Yes |

### Message Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/messages/` | List messages | Yes |
| POST | `/api/messages/` | Send message | Yes |
| GET | `/api/messages/{id}/` | Get message detail | Yes |
| GET | `/api/messages/conversations/` | List conversations | Yes |
| GET | `/api/messages/conversation/{user_id}/` | Get conversation | Yes |

### Notification Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/notifications/` | List notifications | Yes |
| GET | `/api/notifications/{id}/` | Get notification detail | Yes |
| GET | `/api/notifications/unread-count/` | Get unread count | Yes |
| POST | `/api/notifications/{id}/mark-read/` | Mark as read | Yes |
| POST | `/api/notifications/mark-all-read/` | Mark all as read | Yes |

---

## Quick Start Guide

### 1. Authentication

```python
import requests

BASE_URL = "http://localhost:8000/api"

# Get JWT Token
response = requests.post(
    f"{BASE_URL}/auth/token/",
    json={"username": "user1", "password": "password123"}
)
tokens = response.json()
access_token = tokens['access']
```

### 2. Use Token

```python
headers = {"Authorization": f"Bearer {access_token}"}

# List disputes
response = requests.get(f"{BASE_URL}/disputes/", headers=headers)
disputes = response.json()
```

### 3. Send Message

```python
data = {
    "receiver": 2,
    "message": "Hello!"
}
response = requests.post(
    f"{BASE_URL}/messages/",
    json=data,
    headers=headers
)
```

### 4. Get Notifications

```python
# Get unread count
response = requests.get(
    f"{BASE_URL}/notifications/unread-count/",
    headers=headers
)
unread_count = response.json()['unread_count']
```

---

## Troubleshooting

### Common Issues

#### 1. Authentication Errors

**Problem:** `401 Unauthorized`

**Solutions:**
- Verify token is included in Authorization header
- Check token hasn't expired (refresh if needed)
- Ensure token format: `Bearer {token}`

#### 2. Permission Errors

**Problem:** `403 Forbidden`

**Solutions:**
- Check user has required permissions
- Verify user role (staff vs regular user)
- Check endpoint-specific permission requirements

#### 3. Rate Limiting

**Problem:** `429 Too Many Requests`

**Solutions:**
- Wait for rate limit to reset
- Use authenticated requests (higher limits)
- Implement exponential backoff in client

#### 4. Validation Errors

**Problem:** `400 Bad Request`

**Solutions:**
- Check request body format (JSON)
- Verify required fields are present
- Check field types and constraints

### Getting Help

1. **Check Swagger UI:** `http://localhost:8000/api/schema/swagger-ui/`
2. **Review Examples:** `API_USAGE_EXAMPLES.md`
3. **Run Tests:** `python manage.py test api.tests`
4. **Check Logs:** Django server logs for detailed errors

---

## File Structure

```
Arena2/
├── api/
│   ├── serializers.py      # Dispute, Message, Notification serializers
│   ├── views.py            # ViewSets with custom actions
│   ├── urls.py             # API URL routing
│   └── tests.py            # API test suite (28 tests)
├── postman/
│   └── PlayyArena_API.postman_collection.json
├── API_USAGE_EXAMPLES.md   # Code examples
├── DAY19_GUIDE.md          # Day 19 implementation guide
├── DAY19_STEPS.md          # Day 19 step-by-step checklist
├── DAY20_GUIDE.md          # Day 20 implementation guide
└── DAY20_STEPS.md          # Day 20 step-by-step checklist
```

---

## Summary

### Day 19 Achievements
- ✅ Dispute API (3 endpoints)
- ✅ Messaging API (5 endpoints)
- ✅ Notification API (5 endpoints)
- ✅ Proper permissions and filtering
- ✅ Automatic notification creation

### Day 20 Achievements
- ✅ Swagger/OpenAPI documentation
- ✅ API test suite (28 tests)
- ✅ Postman collection (24 endpoints)
- ✅ Rate limiting configuration
- ✅ Comprehensive usage examples

### Total Deliverables
- **13 new API endpoints** (Day 19)
- **28 automated tests** (Day 20)
- **Interactive documentation** (Swagger/ReDoc)
- **Postman collection** (24 endpoints)
- **Usage examples** (3 languages)
- **Rate limiting** (API protection)

---

## Next Steps

After Day 19 & 20:
- **Day 21:** API Security & Optimization
  - Review API security
  - Optimize queries
  - Add caching
  - Performance testing

---

**Last Updated:** 2026-01-31  
**API Version:** 1.0.0  
**Status:** ✅ Complete

