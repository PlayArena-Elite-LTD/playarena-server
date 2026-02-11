# Step 4: Testing Day 19 API Endpoints

## Overview

Step 4 involves testing all the API endpoints we've created for Dispute, Messaging, and Notification APIs.

## Pre-Testing Checklist

Before testing, ensure:
- [x] All serializers are created (Step 1)
- [x] All ViewSets are created (Step 2)
- [x] Router is configured (Step 3)
- [ ] Django server can start without errors
- [ ] Database migrations are up to date
- [ ] You have test user accounts (regular user and support staff)

---

## Step 4.1: Start Django Server

```bash
cd Arena2
python manage.py runserver
```

**Expected Result:**
- Server starts on `http://localhost:8000/`
- No import errors or syntax errors
- All URLs load correctly

---

## Step 4.2: Get JWT Authentication Token

Before testing any endpoints, you need to authenticate and get a JWT token.

### Request:
```http
POST http://localhost:8000/api/auth/token/
Content-Type: application/json

{
    "username": "your_username",
    "password": "your_password"
}
```

### Expected Response:
```json
{
    "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

**Save the `access` token** - you'll need it for all subsequent requests.

---

## Step 4.3: Test Dispute Endpoints

### 4.3.1 List Disputes

**Request:**
```http
GET http://localhost:8000/api/disputes/
Authorization: Bearer {your_access_token}
```

**Expected Behavior:**
- **Support Staff:** Returns all disputes
- **Regular Users:** Returns only disputes for their matches
- Can filter by status: `?status=OPEN` or `?status=RESOLVED`

**Expected Response:**
```json
[
    {
        "id": 1,
        "match_id": 5,
        "match_game": "FIFA 25",
        "match_amount": "50.00",
        "match_status": "DISPUTED",
        "status": "OPEN",
        "created_at": "2025-01-20T10:30:00Z",
        "assigned_to": null,
        "assigned_to_username": null,
        "resolution_notes": null,
        "resolved_at": null,
        "creator_username": "user1",
        "joiner_username": "user2"
    }
]
```

### 4.3.2 Get Dispute Detail

**Request:**
```http
GET http://localhost:8000/api/disputes/1/
Authorization: Bearer {your_access_token}
```

**Expected Response:**
```json
{
    "id": 1,
    "match_id": 5,
    "match_game": "FIFA 25",
    "match_amount": "50.00",
    "match_status": "DISPUTED",
    "status": "OPEN",
    "created_at": "2025-01-20T10:30:00Z",
    "assigned_to": null,
    "assigned_to_username": null,
    "resolution_notes": null,
    "resolved_at": null,
    "creator_username": "user1",
    "joiner_username": "user2"
}
```

### 4.3.3 Resolve Dispute (Support Staff Only)

**Request:**
```http
POST http://localhost:8000/api/disputes/1/resolve/
Authorization: Bearer {support_staff_access_token}
Content-Type: application/json

{
    "status": "RESOLVED",
    "resolution_notes": "Dispute resolved in favor of creator. Evidence reviewed."
}
```

**Expected Response:**
```json
{
    "id": 1,
    "match_id": 5,
    "match_game": "FIFA 25",
    "match_amount": "50.00",
    "match_status": "DISPUTED",
    "status": "RESOLVED",
    "created_at": "2025-01-20T10:30:00Z",
    "resolved_at": "2025-01-20T11:00:00Z",
    "resolution_notes": "Dispute resolved in favor of creator. Evidence reviewed.",
    ...
}
```

**Note:** This should also create notifications for match participants.

---

## Step 4.4: Test Messaging Endpoints

### 4.4.1 Send Message

**Request:**
```http
POST http://localhost:8000/api/messages/
Authorization: Bearer {your_access_token}
Content-Type: application/json

{
    "receiver": 2,
    "message": "Hello! How are you doing?"
}
```

**Expected Response:**
```json
{
    "id": 1,
    "sender": 1,
    "sender_username": "user1",
    "receiver": 2,
    "receiver_username": "user2",
    "message": "Hello! How are you doing?",
    "created_at": "2025-01-20T10:30:00Z",
    "is_read": false
}
```

**Note:** This should create a notification for the receiver.

### 4.4.2 List All Messages

**Request:**
```http
GET http://localhost:8000/api/messages/
Authorization: Bearer {your_access_token}
```

**Expected Response:**
```json
[
    {
        "id": 1,
        "sender": 1,
        "sender_username": "user1",
        "receiver": 2,
        "receiver_username": "user2",
        "message": "Hello!",
        "created_at": "2025-01-20T10:30:00Z",
        "is_read": false
    },
    {
        "id": 2,
        "sender": 2,
        "sender_username": "user2",
        "receiver": 1,
        "receiver_username": "user1",
        "message": "Hi there!",
        "created_at": "2025-01-20T10:35:00Z",
        "is_read": true
    }
]
```

### 4.4.3 List Conversations

**Request:**
```http
GET http://localhost:8000/api/messages/conversations/
Authorization: Bearer {your_access_token}
```

**Expected Response:**
```json
[
    {
        "user_id": 2,
        "username": "user2",
        "latest_message": {
            "id": 2,
            "sender": 2,
            "sender_username": "user2",
            "receiver": 1,
            "receiver_username": "user1",
            "message": "Hi there!",
            "created_at": "2025-01-20T10:35:00Z",
            "is_read": true
        },
        "unread_count": 0
    }
]
```

### 4.4.4 Get Conversation with User

**Request:**
```http
GET http://localhost:8000/api/messages/conversation/2/
Authorization: Bearer {your_access_token}
```

**Expected Response:**
```json
[
    {
        "id": 1,
        "sender": 1,
        "sender_username": "user1",
        "receiver": 2,
        "receiver_username": "user2",
        "message": "Hello!",
        "created_at": "2025-01-20T10:30:00Z",
        "is_read": true
    },
    {
        "id": 2,
        "sender": 2,
        "sender_username": "user2",
        "receiver": 1,
        "receiver_username": "user1",
        "message": "Hi there!",
        "created_at": "2025-01-20T10:35:00Z",
        "is_read": true
    }
]
```

**Note:** Messages should be automatically marked as read when viewing the conversation.

---

## Step 4.5: Test Notification Endpoints

### 4.5.1 List Notifications

**Request:**
```http
GET http://localhost:8000/api/notifications/
Authorization: Bearer {your_access_token}
```

**Expected Response:**
```json
[
    {
        "id": 1,
        "message": "You have a new message from user2",
        "created_at": "2025-01-20T10:30:00Z",
        "is_read": false
    },
    {
        "id": 2,
        "message": "Dispute for match ABC123 has been resolved.",
        "created_at": "2025-01-20T09:00:00Z",
        "is_read": true
    }
]
```

### 4.5.2 Get Unread Count

**Request:**
```http
GET http://localhost:8000/api/notifications/unread-count/
Authorization: Bearer {your_access_token}
```

**Expected Response:**
```json
{
    "unread_count": 1
}
```

### 4.5.3 Mark Notification as Read

**Request:**
```http
POST http://localhost:8000/api/notifications/1/mark-read/
Authorization: Bearer {your_access_token}
```

**Expected Response:**
```json
{
    "message": "Notification marked as read."
}
```

### 4.5.4 Mark All Notifications as Read

**Request:**
```http
POST http://localhost:8000/api/notifications/mark-all-read/
Authorization: Bearer {your_access_token}
```

**Expected Response:**
```json
{
    "message": "3 notifications marked as read."
}
```

---

## Testing Tools

You can use any of these tools to test the API:

1. **Postman** - GUI tool for API testing
2. **curl** - Command-line tool
3. **HTTPie** - User-friendly command-line tool
4. **Thunder Client** - VS Code extension
5. **Django REST Framework Browsable API** - Visit endpoints in browser (requires authentication)

### Example with curl:

```bash
# Get token
curl -X POST http://localhost:8000/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "user1", "password": "password123"}'

# List disputes
curl -X GET http://localhost:8000/api/disputes/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

## Common Issues & Solutions

### Issue: 401 Unauthorized
**Solution:** Make sure you're including the `Authorization: Bearer {token}` header

### Issue: 403 Forbidden
**Solution:** 
- For resolve dispute: Make sure user has `is_support_staff=True` or `is_staff=True`
- For other endpoints: Check user has proper permissions

### Issue: 404 Not Found
**Solution:** 
- Check the endpoint URL is correct
- Verify the router is properly configured
- Check that the ViewSet is registered

### Issue: 400 Bad Request
**Solution:** 
- Check request body format (JSON)
- Verify required fields are provided
- Check field validation errors in response

### Issue: Messages not marking as read
**Solution:** 
- Verify `ReadMessage` model exists
- Check the conversation endpoint is being called (auto-marks as read)

---

## Verification Checklist

After testing, verify:

- [ ] Can get JWT token successfully
- [ ] Can list disputes (with proper filtering)
- [ ] Can get dispute detail
- [ ] Support staff can resolve disputes
- [ ] Can send messages
- [ ] Can list all messages
- [ ] Can list conversations
- [ ] Can get conversation with user
- [ ] Messages auto-mark as read when viewing conversation
- [ ] Can list notifications
- [ ] Can get unread count
- [ ] Can mark notification as read
- [ ] Can mark all notifications as read
- [ ] Notifications are created when:
  - [ ] Dispute is resolved
  - [ ] Message is sent
- [ ] Permissions work correctly (users can only see their own data)
- [ ] Support staff can see all disputes

---

## Next Steps

Once all tests pass:
1. ✅ Step 1: Serializers - Complete
2. ✅ Step 2: ViewSets - Complete
3. ✅ Step 3: URLs - Complete
4. ✅ Step 4: Testing - Complete

**Day 19 is complete!** 🎉

All three APIs (Dispute, Messaging, Notification) are now fully functional and tested.

