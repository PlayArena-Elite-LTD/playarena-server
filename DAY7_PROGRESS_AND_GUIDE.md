# Day 7: Evidence Upload System (Backend) - Progress & Implementation Guide

## Current Status

### 📋 Overview
Day 7 focuses on implementing the **Evidence Upload System (Backend)** - a critical component for dispute resolution. Players will be able to upload screenshots/videos as proof of match results, which support staff will review during disputes.

### 🎯 Objectives
- Configure file storage (local for development, cloud-ready for production)
- Create Evidence model to track uploaded files
- Add evidence_file field to MatchResult model
- Implement secure file upload views with validation
- Create evidence retrieval endpoints
- Integrate evidence display in dispute views

### ⚠️ Current State
- **MatchResult model exists** but lacks evidence_file field
- **Dispute model exists** in panel app
- **No Evidence model** yet
- **No file storage configured** yet
- **No file upload views** yet

---

## Task Breakdown

### Task 1: Configure File Storage
**Status**: Pending  
**Priority**: High (foundation for all file operations)

**Implementation Steps**:
1. Install required packages:
   ```bash
   pip install django-storages boto3  # For AWS S3 (production)
   # OR
   pip install cloudinary  # For Cloudinary (alternative)
   ```
2. Update `core/settings.py`:
   - Add `MEDIA_URL` and `MEDIA_ROOT` for local development
   - Configure `DEFAULT_FILE_STORAGE` (local for dev, S3/Cloudinary for production)
   - Add file size limits in settings
   - Add allowed file types in settings
3. Update `core/urls.py`:
   - Add media file serving in development (DEBUG=True only)
4. Create `.env` variables for production storage:
   - `AWS_ACCESS_KEY_ID` (if using S3)
   - `AWS_SECRET_ACCESS_KEY` (if using S3)
   - `AWS_STORAGE_BUCKET_NAME` (if using S3)
   - `CLOUDINARY_URL` (if using Cloudinary)

**Files to modify**:
- `core/settings.py`
- `core/urls.py`
- `requirements.txt` (add storage packages)

**Security considerations**:
- Never serve media files directly in production (use CDN/storage service)
- Validate file types server-side (not just client-side)
- Set appropriate file size limits
- Sanitize file names to prevent path traversal

**Test approach**:
- Test file upload with valid files
- Test file upload with invalid file types
- Test file upload with oversized files
- Test file retrieval
- **Delete test file after committing**

---

### Task 2: Create Evidence Model
**Status**: Pending  
**Priority**: High (core data model)

**Implementation Steps**:
1. Create `Evidence` model in `matches/models.py`:
   ```python
   class Evidence(models.Model):
       FILE_TYPE_CHOICES = [
           ('IMAGE', 'Image'),
           ('VIDEO', 'Video'),
       ]
       
       match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='evidence')
       user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='evidence_submissions')
       file = models.FileField(upload_to='evidence/%Y/%m/%d/')
       file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES)
       uploaded_at = models.DateTimeField(auto_now_add=True)
       description = models.TextField(blank=True, null=True)  # Optional description
       is_verified = models.BooleanField(default=False)  # For support staff verification
       
       class Meta:
           ordering = ['-uploaded_at']
           indexes = [
               models.Index(fields=['match', 'user']),
               models.Index(fields=['uploaded_at']),
           ]
   ```
2. Add security fields:
   - `file_size` (PositiveIntegerField) - Store file size for validation
   - `file_hash` (CharField) - SHA256 hash for integrity checking
   - `ip_address` (GenericIPAddressField) - Track upload source
   - `user_agent` (CharField) - Track upload client
3. Add validation methods:
   - `clean()` method to validate file type and size
   - `generate_file_hash()` method for integrity checking
4. Add properties:
   - `file_size_mb` - Human-readable file size
   - `is_image` - Check if file is image
   - `is_video` - Check if file is video

**Files to create/modify**:
- `matches/models.py` (add Evidence model)
- `matches/migrations/0006_evidence.py` (create migration)

**Security considerations**:
- Validate file types server-side
- Validate file size before saving
- Generate file hash for integrity
- Store file in organized directory structure (by date)
- Track upload metadata (IP, user agent) for security

**Test approach**:
- Test Evidence model creation
- Test file type validation
- Test file size validation
- Test file hash generation
- **Delete test file after committing**

---

### Task 3: Add evidence_file Field to MatchResult
**Status**: Pending  
**Priority**: High (links evidence to match results)

**Implementation Steps**:
1. Update `MatchResult` model in `matches/models.py`:
   - Add `evidence_file` field (FileField, optional, for backward compatibility)
   - OR: Use Evidence model relationship (preferred - multiple evidence per result)
2. Create migration:
   ```bash
   python manage.py makemigrations matches
   ```
3. Update existing MatchResult instances (if any):
   - Migration should handle null values gracefully

**Files to modify**:
- `matches/models.py` (update MatchResult model)
- `matches/migrations/0007_matchresult_evidence.py` (create migration)

**Note**: Consider if we want single file (evidence_file) or multiple files (Evidence model relationship). Recommendation: Use Evidence model for multiple evidence support.

**Test approach**:
- Test MatchResult with evidence
- Test MatchResult without evidence (backward compatibility)
- **Delete test file after committing**

---

### Task 4: Create File Upload View with Validation
**Status**: Pending  
**Priority**: High (core functionality)

**Implementation Steps**:
1. Create `upload_evidence` view in `matches/views.py`:
   - Handle POST requests with file upload
   - Validate file type (images: jpg, jpeg, png, gif; videos: mp4, mov, avi)
   - Validate file size (images: max 10MB, videos: max 50MB)
   - Generate file hash
   - Save Evidence instance
   - Return JSON response with file info
2. Add security features:
   - Rate limiting (e.g., 10 uploads per hour per user)
   - IP address tracking
   - User agent tracking
   - File content validation (not just extension)
   - Virus scanning (optional, for production)
3. Add error handling:
   - Invalid file type
   - File too large
   - Upload failure
   - Storage errors
4. Create form class in `matches/forms.py`:
   - `EvidenceUploadForm` with file field and validation

**Files to create/modify**:
- `matches/views.py` (add upload_evidence view)
- `matches/forms.py` (add EvidenceUploadForm)
- `matches/urls.py` (add upload_evidence URL)

**Security considerations**:
- Validate file content, not just extension (use python-magic or file signatures)
- Limit file size to prevent DoS attacks
- Rate limit uploads to prevent abuse
- Sanitize file names
- Store files outside web root (or use storage service)
- Track upload metadata for audit

**Test approach**:
- Test valid file uploads (images and videos)
- Test invalid file types
- Test oversized files
- Test rate limiting
- Test file hash generation
- **Delete test file after committing**

---

### Task 5: Add File Size and Type Validation
**Status**: Pending  
**Priority**: High (security)

**Implementation Steps**:
1. Create validation constants in `matches/models.py` or `matches/utils.py`:
   ```python
   # File size limits (in bytes)
   MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
   MAX_VIDEO_SIZE = 50 * 1024 * 1024  # 50MB
   
   # Allowed file types
   ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
   ALLOWED_VIDEO_TYPES = ['video/mp4', 'video/quicktime', 'video/x-msvideo']
   ```
2. Add validation in Evidence model `clean()` method
3. Add validation in EvidenceUploadForm `clean_file()` method
4. Add validation in upload_evidence view
5. Create utility function `validate_evidence_file(file)`:
   - Check file type (MIME type, not just extension)
   - Check file size
   - Return validation result

**Files to create/modify**:
- `matches/models.py` (add validation to Evidence model)
- `matches/forms.py` (add validation to form)
- `matches/views.py` (add validation to view)
- `matches/utils.py` (create if doesn't exist, add validation function)

**Security considerations**:
- Validate MIME type, not just file extension
- Check file size before saving
- Use file signatures (magic bytes) for type detection
- Reject executable files and scripts

**Test approach**:
- Test with valid file types
- Test with invalid file types
- Test with oversized files
- Test with files that have wrong extensions
- **Delete test file after committing**

---

### Task 6: Implement File Upload to Storage
**Status**: Pending  
**Priority**: High (core functionality)

**Implementation Steps**:
1. Configure storage backend in `core/settings.py`:
   - Local storage for development
   - S3/Cloudinary for production (optional)
2. Update Evidence model file field:
   - Use `upload_to` parameter for organized storage
   - Format: `evidence/{year}/{month}/{day}/{filename}`
3. Implement file upload in view:
   - Save file using Django's FileField
   - Handle storage errors gracefully
   - Generate file hash after upload
   - Update Evidence instance with file info
4. Add file cleanup:
   - Delete old files when Evidence is deleted
   - Handle orphaned files (optional cleanup job)

**Files to modify**:
- `core/settings.py` (storage configuration)
- `matches/models.py` (Evidence model file field)
- `matches/views.py` (upload_evidence view)

**Security considerations**:
- Store files outside web root (or use storage service)
- Use organized directory structure
- Generate unique file names to prevent conflicts
- Set appropriate file permissions

**Test approach**:
- Test file upload to local storage
- Test file retrieval
- Test file deletion
- Test storage error handling
- **Delete test file after committing**

---

### Task 7: Create Evidence Retrieval Endpoints
**Status**: Pending  
**Priority**: Medium (for API and display)

**Implementation Steps**:
1. Create `get_evidence` view in `matches/views.py`:
   - GET request to retrieve evidence file
   - Check user permissions (match participant or support staff)
   - Return file response with appropriate headers
   - Add caching headers for performance
2. Create `list_evidence` view:
   - GET request to list all evidence for a match
   - Return JSON with evidence metadata
   - Filter by user (optional)
   - Paginate results
3. Add URL patterns in `matches/urls.py`:
   - `/evidence/<evidence_id>/` - Get evidence file
   - `/evidence/match/<match_id>/` - List evidence for match
   - `/evidence/<evidence_id>/download/` - Download evidence file

**Files to create/modify**:
- `matches/views.py` (add evidence retrieval views)
- `matches/urls.py` (add evidence URLs)

**Security considerations**:
- Verify user has permission to view evidence (match participant or support staff)
- Rate limit evidence retrieval
- Add access logging
- Prevent direct file access (use view to serve files)

**Test approach**:
- Test evidence retrieval for match participants
- Test evidence retrieval for non-participants (should fail)
- Test evidence list endpoint
- Test download endpoint
- **Delete test file after committing**

---

### Task 8: Add Evidence Display in Dispute Views
**Status**: Pending  
**Priority**: High (critical for dispute resolution)

**Implementation Steps**:
1. Update `panel/views.py` (or wherever dispute views are):
   - Add evidence context to dispute detail view
   - Query Evidence objects for the match
   - Group evidence by user (creator vs joiner)
   - Pass evidence to template
2. Update dispute detail template:
   - Display evidence gallery
   - Show evidence metadata (upload time, file type, file size)
   - Add image preview for images
   - Add video player for videos
   - Add download links
3. Create evidence comparison view (optional):
   - Side-by-side display of creator vs joiner evidence
   - Helpful for support staff review

**Files to modify**:
- `panel/views.py` (update dispute views)
- `templates/panel/dispute_detail.html` (add evidence display)
- `templates/panel/evidence_comparison.html` (create if needed)

**Security considerations**:
- Only support staff and match participants can view evidence
- Verify user permissions before displaying
- Sanitize file names in templates

**Test approach**:
- Test evidence display in dispute view
- Test evidence display for match participants
- Test evidence display for non-participants (should fail)
- **Delete test file after committing**

---

### Task 9: Add Evidence Admin Interface
**Status**: Pending  
**Priority**: Low (polish)

**Implementation Steps**:
1. Register Evidence model in `matches/admin.py`:
   - Add EvidenceAdmin class
   - Configure list display (match, user, file_type, uploaded_at, is_verified)
   - Add filters (match, user, file_type, is_verified, uploaded_at)
   - Add search (match, user)
   - Add custom actions (mark_as_verified, mark_as_unverified, delete_evidence)
2. Add custom display methods:
   - `file_preview` - Show thumbnail for images
   - `file_size_display` - Human-readable file size
   - `download_link` - Link to download file
3. Add readonly fields for audit:
   - `uploaded_at`, `ip_address`, `user_agent`, `file_hash`

**Files to modify**:
- `matches/admin.py` (add EvidenceAdmin)

**Test approach**:
- Test admin interface
- Test custom actions
- **Delete test file after committing**

---

### Task 10: Add Evidence Utilities and Helpers
**Status**: Pending  
**Priority**: Low (code quality)

**Implementation Steps**:
1. Create `matches/utils.py` (if doesn't exist):
   - `validate_evidence_file(file)` - File validation utility
   - `get_file_type(file)` - Detect file type from content
   - `generate_file_hash(file)` - Generate SHA256 hash
   - `get_file_size_mb(file)` - Convert bytes to MB
   - `is_valid_image(file)` - Check if file is valid image
   - `is_valid_video(file)` - Check if file is valid video
2. Create `matches/validators.py` (optional):
   - Custom validators for file types and sizes
   - Reusable across forms and models

**Files to create/modify**:
- `matches/utils.py` (create or update)
- `matches/validators.py` (create if needed)

**Test approach**:
- Test utility functions
- Test validators
- **Delete test file after committing**

---

## Security-First Approach

### Critical Security Measures

1. **File Type Validation**:
   - ✅ Validate MIME type (not just extension)
   - ✅ Use file signatures (magic bytes)
   - ✅ Reject executable files and scripts
   - ✅ Whitelist allowed types only

2. **File Size Limits**:
   - ✅ Images: Max 10MB
   - ✅ Videos: Max 50MB
   - ✅ Validate before saving
   - ✅ Prevent DoS attacks

3. **Access Control**:
   - ✅ Only match participants can upload evidence
   - ✅ Only match participants and support staff can view evidence
   - ✅ Rate limit uploads (prevent abuse)
   - ✅ Track upload metadata (IP, user agent)

4. **File Storage**:
   - ✅ Store files outside web root (or use storage service)
   - ✅ Generate unique file names
   - ✅ Organize by date for easy management
   - ✅ Set appropriate file permissions

5. **Data Integrity**:
   - ✅ Generate file hash (SHA256) for integrity checking
   - ✅ Store file metadata for audit
   - ✅ Track upload source (IP, user agent)

---

## Working Pattern

### For Each Task:
1. **Implement the feature** following security-first approach
2. **Write unit tests** for the feature
3. **Run tests** and verify they pass
4. **Delete test file** after committing (per user preference)
5. **Commit** with pattern:
   ```
   [Task Name/Feature]. [What was implemented]. [Security features: list key security measures]. [Code quality: mention patterns followed].
   ```
6. **Move to next task**

### Example Commit Messages:
```
Evidence model with file validation and security tracking. Security features: file type validation, size limits, hash generation, IP tracking. Code quality: atomic transactions, error handling, audit logging.

File upload view with comprehensive validation. Security features: MIME type validation, rate limiting, file signature checking, access control. Code quality: reusable utilities, error sanitization.

Evidence retrieval endpoints with access control. Security features: permission verification, rate limiting, access logging. Code quality: DRY principles, proper error handling.
```

---

## File Structure

### Files to Create:
- `matches/models.py` (add Evidence model)
- `matches/migrations/0006_evidence.py`
- `matches/migrations/0007_matchresult_evidence.py` (if adding field)
- `matches/forms.py` (add EvidenceUploadForm)
- `matches/utils.py` (create if doesn't exist)
- `matches/validators.py` (optional)
- `templates/panel/evidence_comparison.html` (optional)

### Files to Modify:
- `core/settings.py` (storage configuration)
- `core/urls.py` (media file serving)
- `matches/models.py` (add Evidence model, update MatchResult)
- `matches/views.py` (add upload/retrieval views)
- `matches/urls.py` (add evidence URLs)
- `matches/admin.py` (add EvidenceAdmin)
- `panel/views.py` (update dispute views)
- `templates/panel/dispute_detail.html` (add evidence display)
- `requirements.txt` (add storage packages)

---

## Testing Strategy

### Unit Tests:
- Model validation (file type, size)
- Form validation
- Utility functions
- Validators

### Integration Tests:
- File upload flow
- File retrieval flow
- Evidence display in disputes
- Access control

### Security Tests:
- Invalid file type rejection
- Oversized file rejection
- Unauthorized access prevention
- Rate limiting
- File hash integrity

---

## Configuration

### Required Settings (core/settings.py):
```python
# Media files configuration
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# File storage (development - local)
DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

# File size limits (in bytes)
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_VIDEO_SIZE = 50 * 1024 * 1024  # 50MB

# Allowed file types
ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
ALLOWED_VIDEO_TYPES = ['video/mp4', 'video/quicktime', 'video/x-msvideo']
```

### Production Storage (Optional - AWS S3):
```python
# Install: pip install django-storages boto3
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY')
AWS_STORAGE_BUCKET_NAME = config('AWS_STORAGE_BUCKET_NAME')
AWS_S3_REGION_NAME = 'us-east-1'  # Adjust as needed
```

---

## Dependencies

### Required Packages:
```bash
# For file type detection (recommended)
pip install python-magic-bin  # Windows
# OR
pip install python-magic  # Linux/Mac

# For production storage (optional)
pip install django-storages boto3  # AWS S3
# OR
pip install cloudinary  # Cloudinary
```

Add to `requirements.txt`:
```
python-magic-bin  # or python-magic for Linux/Mac
django-storages  # Optional, for S3
boto3  # Optional, for S3
```

---

## Priority Order

**High Priority (Complete First)**:
1. Task 1: Configure File Storage
2. Task 2: Create Evidence Model
3. Task 4: Create File Upload View
4. Task 5: Add File Validation
5. Task 6: Implement File Upload to Storage
6. Task 8: Add Evidence Display in Dispute Views

**Medium Priority**:
7. Task 3: Add evidence_file Field to MatchResult
8. Task 7: Create Evidence Retrieval Endpoints

**Low Priority (Polish)**:
9. Task 9: Add Evidence Admin Interface
10. Task 10: Add Evidence Utilities

---

## Quick Reference

### Key Models:
- **Evidence**: Stores uploaded files with metadata
- **MatchResult**: Links to evidence (via ForeignKey relationship)

### Key Views:
- `upload_evidence`: Handle file uploads
- `get_evidence`: Retrieve evidence file
- `list_evidence`: List evidence for a match

### Key Security Features:
- File type validation (MIME type + file signatures)
- File size limits
- Rate limiting
- Access control
- File hash for integrity
- IP and user agent tracking

---

## Getting Started

1. **Start with Task 1** (Configure File Storage) - Foundation for everything
2. **Follow security-first approach** for every implementation
3. **Write tests, verify, delete tests, commit** for each task
4. **Use commit message pattern** shown above
5. **Work on one task at a time** - complete, test, commit, then move to next

---

**Good luck completing Day 7! Remember: Security first, validate everything, test thoroughly.** 🚀
