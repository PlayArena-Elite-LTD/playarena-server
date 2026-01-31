# PlayyArena API Usage Examples

This document provides code examples for using the PlayyArena API in different programming languages and tools.

## Table of Contents

- [Python Examples](#python-examples)
- [JavaScript Examples](#javascript-examples)
- [cURL Examples](#curl-examples)
- [Error Handling](#error-handling)
- [Best Practices](#best-practices)

---

## Python Examples

### Setup

```python
import requests
import json

BASE_URL = "http://localhost:8000/api"

# Helper function to get headers with token
def get_headers(access_token=None):
    headers = {"Content-Type": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers
```

### Authentication

#### Register User

```python
def register_user(username, email, password, password2):
    """Register a new user"""
    url = f"{BASE_URL}/auth/register/"
    data = {
        "username": username,
        "email": email,
        "password": password,
        "password2": password2
    }
    response = requests.post(url, json=data, headers=get_headers())
    return response.json() if response.status_code == 201 else response.text

# Example usage
result = register_user(
    username="newuser",
    email="newuser@example.com",
    password="securepassword123",
    password2="securepassword123"
)
print(result)
```

#### Get JWT Token

```python
def get_jwt_token(username, password):
    """Get JWT access and refresh tokens"""
    url = f"{BASE_URL}/auth/token/"
    data = {
        "username": username,
        "password": password
    }
    response = requests.post(url, json=data, headers=get_headers())
    if response.status_code == 200:
        tokens = response.json()
        return tokens['access'], tokens['refresh']
    else:
        raise Exception(f"Authentication failed: {response.text}")

# Example usage
access_token, refresh_token = get_jwt_token("user1", "password123")
print(f"Access Token: {access_token[:50]}...")
```

#### Refresh Token

```python
def refresh_access_token(refresh_token):
    """Refresh the access token using refresh token"""
    url = f"{BASE_URL}/auth/token/refresh/"
    data = {"refresh": refresh_token}
    response = requests.post(url, json=data, headers=get_headers())
    if response.status_code == 200:
        return response.json()['access']
    else:
        raise Exception(f"Token refresh failed: {response.text}")

# Example usage
new_access_token = refresh_access_token(refresh_token)
```

#### Change Password

```python
def change_password(access_token, old_password, new_password, new_password2):
    """Change user password"""
    url = f"{BASE_URL}/auth/change-password/"
    data = {
        "old_password": old_password,
        "new_password": new_password,
        "new_password2": new_password2
    }
    response = requests.post(
        url,
        json=data,
        headers=get_headers(access_token)
    )
    return response.json() if response.status_code == 200 else response.text

# Example usage
result = change_password(
    access_token,
    old_password="oldpassword123",
    new_password="newpassword123",
    new_password2="newpassword123"
)
```

#### Request Password Reset

```python
def request_password_reset(email):
    """Request password reset email"""
    url = f"{BASE_URL}/auth/password-reset/"
    data = {"email": email}
    response = requests.post(url, json=data, headers=get_headers())
    return response.json() if response.status_code == 200 else response.text

# Example usage
result = request_password_reset("user@example.com")
```

### Users

#### Get Current User

```python
def get_current_user(access_token):
    """Get current authenticated user information"""
    url = f"{BASE_URL}/me/"
    response = requests.get(url, headers=get_headers(access_token))
    return response.json() if response.status_code == 200 else response.text

# Example usage
user = get_current_user(access_token)
print(f"Username: {user['username']}, Email: {user['email']}")
```

#### Get My Profile

```python
def get_my_profile(access_token):
    """Get current user's profile"""
    url = f"{BASE_URL}/me/profile/"
    response = requests.get(url, headers=get_headers(access_token))
    return response.json() if response.status_code == 200 else response.text

# Example usage
profile = get_my_profile(access_token)
print(profile)
```

#### Update My Profile

```python
def update_my_profile(access_token, first_name=None, last_name=None, phone_number=None):
    """Update current user's profile"""
    url = f"{BASE_URL}/me/profile/"
    data = {}
    if first_name:
        data["first_name"] = first_name
    if last_name:
        data["last_name"] = last_name
    if phone_number:
        data["phone_number"] = phone_number
    
    response = requests.put(
        url,
        json=data,
        headers=get_headers(access_token)
    )
    return response.json() if response.status_code == 200 else response.text

# Example usage
result = update_my_profile(
    access_token,
    first_name="John",
    last_name="Doe",
    phone_number="+1234567890"
)
```

#### List Users

```python
def list_users(access_token):
    """List all users (public information only)"""
    url = f"{BASE_URL}/users/"
    response = requests.get(url, headers=get_headers(access_token))
    return response.json() if response.status_code == 200 else response.text

# Example usage
users = list_users(access_token)
for user in users:
    print(f"{user['username']} - {user['email']}")
```

#### Get User Detail

```python
def get_user_detail(access_token, user_id):
    """Get detailed information about a specific user"""
    url = f"{BASE_URL}/users/{user_id}/"
    response = requests.get(url, headers=get_headers(access_token))
    return response.json() if response.status_code == 200 else response.text

# Example usage
user = get_user_detail(access_token, user_id=2)
print(user)
```

### Matches

#### Get My Matches

```python
def get_my_matches(access_token):
    """Get all matches where current user is creator or joiner"""
    url = f"{BASE_URL}/my-matches/"
    response = requests.get(url, headers=get_headers(access_token))
    return response.json() if response.status_code == 200 else response.text

# Example usage
matches = get_my_matches(access_token)
for match in matches:
    print(f"Match {match['id']}: {match['game']} - {match['status']}")
```

### Disputes

#### List Disputes

```python
def list_disputes(access_token, status=None):
    """List disputes. Support staff see all, regular users see only their own."""
    url = f"{BASE_URL}/disputes/"
    params = {}
    if status:
        params["status"] = status  # OPEN, PENDING, or RESOLVED
    
    response = requests.get(
        url,
        headers=get_headers(access_token),
        params=params
    )
    return response.json() if response.status_code == 200 else response.text

# Example usage
disputes = list_disputes(access_token, status="OPEN")
for dispute in disputes:
    print(f"Dispute {dispute['id']}: {dispute['status']}")
```

#### Get Dispute Detail

```python
def get_dispute_detail(access_token, dispute_id):
    """Get detailed information about a specific dispute"""
    url = f"{BASE_URL}/disputes/{dispute_id}/"
    response = requests.get(url, headers=get_headers(access_token))
    return response.json() if response.status_code == 200 else response.text

# Example usage
dispute = get_dispute_detail(access_token, dispute_id=1)
print(dispute)
```

#### Resolve Dispute (Staff Only)

```python
def resolve_dispute(access_token, dispute_id, status, resolution_notes):
    """Resolve a dispute. Only support staff can resolve disputes."""
    url = f"{BASE_URL}/disputes/{dispute_id}/resolve/"
    data = {
        "status": status,  # RESOLVED or PENDING
        "resolution_notes": resolution_notes
    }
    response = requests.post(
        url,
        json=data,
        headers=get_headers(access_token)
    )
    return response.json() if response.status_code == 200 else response.text

# Example usage
result = resolve_dispute(
    access_token,
    dispute_id=1,
    status="RESOLVED",
    resolution_notes="Dispute resolved in favor of creator. Evidence reviewed."
)
```

### Messages

#### Send Message

```python
def send_message(access_token, receiver_id, message):
    """Send a new message to another user"""
    url = f"{BASE_URL}/messages/"
    data = {
        "receiver": receiver_id,
        "message": message
    }
    response = requests.post(
        url,
        json=data,
        headers=get_headers(access_token)
    )
    return response.json() if response.status_code == 201 else response.text

# Example usage
result = send_message(access_token, receiver_id=2, message="Hello! How are you?")
print(result)
```

#### List Messages

```python
def list_messages(access_token):
    """Get all messages where current user is sender or receiver"""
    url = f"{BASE_URL}/messages/"
    response = requests.get(url, headers=get_headers(access_token))
    return response.json() if response.status_code == 200 else response.text

# Example usage
messages = list_messages(access_token)
for message in messages:
    print(f"From {message['sender_username']} to {message['receiver_username']}: {message['message']}")
```

#### Get Message Detail

```python
def get_message_detail(access_token, message_id):
    """Get detailed information about a specific message"""
    url = f"{BASE_URL}/messages/{message_id}/"
    response = requests.get(url, headers=get_headers(access_token))
    return response.json() if response.status_code == 200 else response.text

# Example usage
message = get_message_detail(access_token, message_id=1)
print(message)
```

#### List Conversations

```python
def list_conversations(access_token):
    """Get all conversations with latest message and unread count"""
    url = f"{BASE_URL}/messages/conversations/"
    response = requests.get(url, headers=get_headers(access_token))
    return response.json() if response.status_code == 200 else response.text

# Example usage
conversations = list_conversations(access_token)
for conv in conversations:
    print(f"User {conv['username']}: {conv['unread_count']} unread messages")
```

#### Get Conversation

```python
def get_conversation(access_token, user_id):
    """Get all messages in a conversation with a specific user"""
    url = f"{BASE_URL}/messages/conversation/{user_id}/"
    response = requests.get(url, headers=get_headers(access_token))
    return response.json() if response.status_code == 200 else response.text

# Example usage
messages = get_conversation(access_token, user_id=2)
for msg in messages:
    print(f"{msg['sender_username']}: {msg['message']}")
```

### Notifications

#### List Notifications

```python
def list_notifications(access_token):
    """Get all notifications for current user"""
    url = f"{BASE_URL}/notifications/"
    response = requests.get(url, headers=get_headers(access_token))
    return response.json() if response.status_code == 200 else response.text

# Example usage
notifications = list_notifications(access_token)
for notification in notifications:
    print(f"{notification['message']} - Read: {notification['is_read']}")
```

#### Get Notification Detail

```python
def get_notification_detail(access_token, notification_id):
    """Get detailed information about a specific notification"""
    url = f"{BASE_URL}/notifications/{notification_id}/"
    response = requests.get(url, headers=get_headers(access_token))
    return response.json() if response.status_code == 200 else response.text

# Example usage
notification = get_notification_detail(access_token, notification_id=1)
print(notification)
```

#### Get Unread Count

```python
def get_unread_count(access_token):
    """Get count of unread notifications for current user"""
    url = f"{BASE_URL}/notifications/unread-count/"
    response = requests.get(url, headers=get_headers(access_token))
    if response.status_code == 200:
        return response.json()['unread_count']
    else:
        return None

# Example usage
unread_count = get_unread_count(access_token)
print(f"You have {unread_count} unread notifications")
```

#### Mark Notification as Read

```python
def mark_notification_read(access_token, notification_id):
    """Mark a specific notification as read"""
    url = f"{BASE_URL}/notifications/{notification_id}/mark-read/"
    response = requests.post(url, headers=get_headers(access_token))
    return response.json() if response.status_code == 200 else response.text

# Example usage
result = mark_notification_read(access_token, notification_id=1)
```

#### Mark All Notifications as Read

```python
def mark_all_notifications_read(access_token):
    """Mark all unread notifications for current user as read"""
    url = f"{BASE_URL}/notifications/mark-all-read/"
    response = requests.post(url, headers=get_headers(access_token))
    return response.json() if response.status_code == 200 else response.text

# Example usage
result = mark_all_notifications_read(access_token)
print(result)
```

---

## JavaScript Examples

### Setup

```javascript
const BASE_URL = "http://localhost:8000/api";

// Helper function to get headers with token
function getHeaders(accessToken = null) {
    const headers = {
        'Content-Type': 'application/json'
    };
    if (accessToken) {
        headers['Authorization'] = `Bearer ${accessToken}`;
    }
    return headers;
}
```

### Authentication

#### Register User

```javascript
async function registerUser(username, email, password, password2) {
    const response = await fetch(`${BASE_URL}/auth/register/`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
            username,
            email,
            password,
            password2
        })
    });
    return await response.json();
}

// Example usage
const result = await registerUser(
    "newuser",
    "newuser@example.com",
    "securepassword123",
    "securepassword123"
);
console.log(result);
```

#### Get JWT Token

```javascript
async function getJWTToken(username, password) {
    const response = await fetch(`${BASE_URL}/auth/token/`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ username, password })
    });
    
    if (!response.ok) {
        throw new Error(`Authentication failed: ${response.statusText}`);
    }
    
    const tokens = await response.json();
    return {
        access: tokens.access,
        refresh: tokens.refresh
    };
}

// Example usage
const { access: accessToken, refresh: refreshToken } = await getJWTToken("user1", "password123");
console.log("Access Token:", accessToken.substring(0, 50) + "...");
```

#### Refresh Token

```javascript
async function refreshAccessToken(refreshToken) {
    const response = await fetch(`${BASE_URL}/auth/token/refresh/`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ refresh: refreshToken })
    });
    
    if (!response.ok) {
        throw new Error(`Token refresh failed: ${response.statusText}`);
    }
    
    const data = await response.json();
    return data.access;
}

// Example usage
const newAccessToken = await refreshAccessToken(refreshToken);
```

#### Change Password

```javascript
async function changePassword(accessToken, oldPassword, newPassword, newPassword2) {
    const response = await fetch(`${BASE_URL}/auth/change-password/`, {
        method: 'POST',
        headers: getHeaders(accessToken),
        body: JSON.stringify({
            old_password: oldPassword,
            new_password: newPassword,
            new_password2: newPassword2
        })
    });
    return await response.json();
}

// Example usage
const result = await changePassword(
    accessToken,
    "oldpassword123",
    "newpassword123",
    "newpassword123"
);
```

### Users

#### Get Current User

```javascript
async function getCurrentUser(accessToken) {
    const response = await fetch(`${BASE_URL}/me/`, {
        headers: getHeaders(accessToken)
    });
    return await response.json();
}

// Example usage
const user = await getCurrentUser(accessToken);
console.log(`Username: ${user.username}, Email: ${user.email}`);
```

#### Get My Profile

```javascript
async function getMyProfile(accessToken) {
    const response = await fetch(`${BASE_URL}/me/profile/`, {
        headers: getHeaders(accessToken)
    });
    return await response.json();
}

// Example usage
const profile = await getMyProfile(accessToken);
console.log(profile);
```

#### Update My Profile

```javascript
async function updateMyProfile(accessToken, profileData) {
    const response = await fetch(`${BASE_URL}/me/profile/`, {
        method: 'PUT',
        headers: getHeaders(accessToken),
        body: JSON.stringify(profileData)
    });
    return await response.json();
}

// Example usage
const result = await updateMyProfile(accessToken, {
    first_name: "John",
    last_name: "Doe",
    phone_number: "+1234567890"
});
```

### Disputes

#### List Disputes

```javascript
async function listDisputes(accessToken, status = null) {
    let url = `${BASE_URL}/disputes/`;
    if (status) {
        url += `?status=${status}`;
    }
    
    const response = await fetch(url, {
        headers: getHeaders(accessToken)
    });
    return await response.json();
}

// Example usage
const disputes = await listDisputes(accessToken, "OPEN");
disputes.forEach(dispute => {
    console.log(`Dispute ${dispute.id}: ${dispute.status}`);
});
```

#### Resolve Dispute (Staff Only)

```javascript
async function resolveDispute(accessToken, disputeId, status, resolutionNotes) {
    const response = await fetch(`${BASE_URL}/disputes/${disputeId}/resolve/`, {
        method: 'POST',
        headers: getHeaders(accessToken),
        body: JSON.stringify({
            status,
            resolution_notes: resolutionNotes
        })
    });
    return await response.json();
}

// Example usage
const result = await resolveDispute(
    accessToken,
    1,
    "RESOLVED",
    "Dispute resolved in favor of creator."
);
```

### Messages

#### Send Message

```javascript
async function sendMessage(accessToken, receiverId, message) {
    const response = await fetch(`${BASE_URL}/messages/`, {
        method: 'POST',
        headers: getHeaders(accessToken),
        body: JSON.stringify({
            receiver: receiverId,
            message
        })
    });
    return await response.json();
}

// Example usage
const result = await sendMessage(accessToken, 2, "Hello! How are you?");
```

#### List Conversations

```javascript
async function listConversations(accessToken) {
    const response = await fetch(`${BASE_URL}/messages/conversations/`, {
        headers: getHeaders(accessToken)
    });
    return await response.json();
}

// Example usage
const conversations = await listConversations(accessToken);
conversations.forEach(conv => {
    console.log(`User ${conv.username}: ${conv.unread_count} unread messages`);
});
```

### Notifications

#### Get Unread Count

```javascript
async function getUnreadCount(accessToken) {
    const response = await fetch(`${BASE_URL}/notifications/unread-count/`, {
        headers: getHeaders(accessToken)
    });
    const data = await response.json();
    return data.unread_count;
}

// Example usage
const unreadCount = await getUnreadCount(accessToken);
console.log(`You have ${unreadCount} unread notifications`);
```

#### Mark All Notifications as Read

```javascript
async function markAllNotificationsRead(accessToken) {
    const response = await fetch(`${BASE_URL}/notifications/mark-all-read/`, {
        method: 'POST',
        headers: getHeaders(accessToken)
    });
    return await response.json();
}

// Example usage
const result = await markAllNotificationsRead(accessToken);
```

---

## cURL Examples

### Authentication

#### Register User

```bash
curl -X POST http://localhost:8000/api/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "newuser",
    "email": "newuser@example.com",
    "password": "securepassword123",
    "password2": "securepassword123"
  }'
```

#### Get JWT Token

```bash
curl -X POST http://localhost:8000/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "user1",
    "password": "password123"
  }'
```

#### Refresh Token

```bash
curl -X POST http://localhost:8000/api/auth/token/refresh/ \
  -H "Content-Type: application/json" \
  -d '{
    "refresh": "YOUR_REFRESH_TOKEN"
  }'
```

#### Change Password

```bash
curl -X POST http://localhost:8000/api/auth/change-password/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "old_password": "oldpassword123",
    "new_password": "newpassword123",
    "new_password2": "newpassword123"
  }'
```

### Users

#### Get Current User

```bash
curl -X GET http://localhost:8000/api/me/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### Get My Profile

```bash
curl -X GET http://localhost:8000/api/me/profile/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### Update My Profile

```bash
curl -X PUT http://localhost:8000/api/me/profile/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "first_name": "John",
    "last_name": "Doe",
    "phone_number": "+1234567890"
  }'
```

#### List Users

```bash
curl -X GET http://localhost:8000/api/users/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### Get User Detail

```bash
curl -X GET http://localhost:8000/api/users/1/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Matches

#### Get My Matches

```bash
curl -X GET http://localhost:8000/api/my-matches/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Disputes

#### List Disputes

```bash
# List all disputes
curl -X GET http://localhost:8000/api/disputes/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"

# List disputes with status filter
curl -X GET "http://localhost:8000/api/disputes/?status=OPEN" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### Get Dispute Detail

```bash
curl -X GET http://localhost:8000/api/disputes/1/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### Resolve Dispute (Staff Only)

```bash
curl -X POST http://localhost:8000/api/disputes/1/resolve/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "RESOLVED",
    "resolution_notes": "Dispute resolved in favor of creator. Evidence reviewed."
  }'
```

### Messages

#### Send Message

```bash
curl -X POST http://localhost:8000/api/messages/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "receiver": 2,
    "message": "Hello! How are you?"
  }'
```

#### List Messages

```bash
curl -X GET http://localhost:8000/api/messages/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### List Conversations

```bash
curl -X GET http://localhost:8000/api/messages/conversations/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### Get Conversation

```bash
curl -X GET http://localhost:8000/api/messages/conversation/2/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Notifications

#### List Notifications

```bash
curl -X GET http://localhost:8000/api/notifications/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### Get Unread Count

```bash
curl -X GET http://localhost:8000/api/notifications/unread-count/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### Mark Notification as Read

```bash
curl -X POST http://localhost:8000/api/notifications/1/mark-read/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### Mark All Notifications as Read

```bash
curl -X POST http://localhost:8000/api/notifications/mark-all-read/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

## Error Handling

### Python Error Handling

```python
import requests

def make_request(method, url, headers=None, data=None):
    """Helper function with error handling"""
    try:
        if method == 'GET':
            response = requests.get(url, headers=headers)
        elif method == 'POST':
            response = requests.post(url, headers=headers, json=data)
        elif method == 'PUT':
            response = requests.put(url, headers=headers, json=data)
        
        response.raise_for_status()  # Raises exception for 4xx/5xx status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error: {e}")
        print(f"Response: {response.text}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request Error: {e}")
        return None

# Example usage
result = make_request(
    'GET',
    f"{BASE_URL}/me/",
    headers=get_headers(access_token)
)
```

### JavaScript Error Handling

```javascript
async function makeRequest(method, url, accessToken = null, data = null) {
    try {
        const options = {
            method: method,
            headers: getHeaders(accessToken)
        };
        
        if (data) {
            options.body = JSON.stringify(data);
        }
        
        const response = await fetch(url, options);
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(`HTTP ${response.status}: ${error.detail || error.message || 'Unknown error'}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error('Request failed:', error);
        throw error;
    }
}

// Example usage
try {
    const user = await makeRequest('GET', `${BASE_URL}/me/`, accessToken);
    console.log(user);
} catch (error) {
    console.error('Failed to get user:', error.message);
}
```

---

## Best Practices

### 1. Token Management

- **Store tokens securely**: Never commit tokens to version control
- **Refresh tokens before expiry**: Access tokens typically expire after 15 minutes
- **Handle token refresh automatically**: Implement automatic token refresh logic

```python
class APIClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.access_token = None
        self.refresh_token = None
    
    def authenticate(self):
        """Authenticate and store tokens"""
        access, refresh = get_jwt_token(self.username, self.password)
        self.access_token = access
        self.refresh_token = refresh
    
    def refresh_token_if_needed(self):
        """Refresh token if expired"""
        # In production, check token expiry before refreshing
        if self.refresh_token:
            self.access_token = refresh_access_token(self.refresh_token)
```

### 2. Rate Limiting

- **Respect rate limits**: API has rate limiting (100/hour for anonymous, 1000/hour for authenticated)
- **Implement retry logic**: Use exponential backoff for rate limit errors

```python
import time

def make_request_with_retry(url, headers, max_retries=3):
    """Make request with retry logic for rate limiting"""
    for attempt in range(max_retries):
        response = requests.get(url, headers=headers)
        if response.status_code == 429:  # Too Many Requests
            wait_time = 2 ** attempt  # Exponential backoff
            print(f"Rate limited. Waiting {wait_time} seconds...")
            time.sleep(wait_time)
            continue
        return response.json()
    raise Exception("Max retries exceeded")
```

### 3. Error Handling

- **Always check response status**: Don't assume requests succeed
- **Handle specific error codes**: 401 (Unauthorized), 403 (Forbidden), 404 (Not Found), etc.
- **Log errors appropriately**: For debugging and monitoring

### 4. Security

- **Use HTTPS in production**: Always use HTTPS for API calls in production
- **Don't expose tokens**: Never log or print access tokens
- **Validate input**: Validate user input before sending to API

### 5. Performance

- **Cache responses when appropriate**: Cache user profile, notifications count, etc.
- **Use pagination**: For large lists, implement pagination
- **Batch requests when possible**: Reduce number of API calls

---

## Additional Resources

- **Swagger UI**: Visit `http://localhost:8000/api/schema/swagger-ui/` for interactive API documentation
- **ReDoc**: Visit `http://localhost:8000/api/schema/redoc/` for alternative API documentation
- **Postman Collection**: Import `postman/PlayyArena_API.postman_collection.json` for easy testing

---

**Last Updated:** 2026-01-31  
**API Version:** 1.0.0

