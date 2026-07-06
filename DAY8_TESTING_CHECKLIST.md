# Day 8: Evidence Upload UI - Testing Checklist

## Overview
This document provides a comprehensive testing checklist for the Evidence Upload UI feature implemented in Day 8.

## Test Environment Setup

### Prerequisites
- Django development server running
- Database migrations applied
- Media files directory configured
- Test user accounts created
- Test matches created (with status 'JOINED')

### Test Data Requirements
- Test images: JPG and PNG files (various sizes)
- Test videos: MP4 and MOV files (various sizes)
- Invalid files: Unsupported formats, oversized files

---

## 1. File Upload Testing

### 1.1 Image Upload (JPG)
- [ ] **Test Case:** Upload a valid JPG image (< 10MB)
  - **Steps:**
    1. Navigate to match detail page for a match with status 'JOINED'
    2. Click "Choose File" or drag-and-drop a JPG file
    3. Verify preview appears
    4. Add optional description
    5. Click "Upload Evidence"
    6. Verify progress bar shows upload progress
    7. Verify success message appears
    8. Verify evidence appears in evidence gallery
  - **Expected Result:** Image uploads successfully, preview works, evidence displays correctly

- [ ] **Test Case:** Upload a valid PNG image (< 10MB)
  - **Steps:** Same as above with PNG file
  - **Expected Result:** PNG uploads successfully

### 1.2 Video Upload (MP4, MOV)
- [ ] **Test Case:** Upload a valid MP4 video (< 50MB)
  - **Steps:**
    1. Navigate to match detail page
    2. Select or drag-and-drop MP4 file
    3. Verify video preview appears with controls
    4. Upload the file
    5. Verify video displays correctly in gallery
  - **Expected Result:** Video uploads successfully, preview works, video plays correctly

- [ ] **Test Case:** Upload a valid MOV video (< 50MB)
  - **Steps:** Same as above with MOV file
  - **Expected Result:** MOV uploads successfully

---

## 2. File Validation Testing

### 2.1 File Size Validation
- [ ] **Test Case:** Upload image > 10MB
  - **Steps:**
    1. Try to upload an image file larger than 10MB
    2. Verify error message appears
    3. Verify file is not uploaded
  - **Expected Result:** Error message: "Image file is too large. Maximum size is 10MB."

- [ ] **Test Case:** Upload video > 50MB
  - **Steps:**
    1. Try to upload a video file larger than 50MB
    2. Verify error message appears
    3. Verify file is not uploaded
  - **Expected Result:** Error message: "Video file is too large. Maximum size is 50MB."

### 2.2 File Type Validation
- [ ] **Test Case:** Upload unsupported image format (e.g., GIF, BMP)
  - **Steps:**
    1. Try to upload a GIF or BMP file
    2. Verify error message appears
    3. Verify file is not uploaded
  - **Expected Result:** Error message: "Image format not supported. Please use JPG or PNG."

- [ ] **Test Case:** Upload unsupported video format (e.g., AVI, WMV)
  - **Steps:**
    1. Try to upload an AVI or WMV file
    2. Verify error message appears
    3. Verify file is not uploaded
  - **Expected Result:** Error message: "Video format not supported. Please use MP4 or MOV."

- [ ] **Test Case:** Upload non-media file (e.g., PDF, DOCX)
  - **Steps:**
    1. Try to upload a PDF or DOCX file
    2. Verify error message appears
    3. Verify file is not uploaded
  - **Expected Result:** Error message: "File type not supported. Please upload an image (JPG, PNG) or video (MP4, MOV)."

---

## 3. Drag-and-Drop Testing

### 3.1 Basic Drag-and-Drop
- [ ] **Test Case:** Drag and drop valid image file
  - **Steps:**
    1. Drag an image file over the drop zone
    2. Verify drop zone highlights (drag-over class applied)
    3. Drop the file
    4. Verify preview appears
    5. Verify file is ready for upload
  - **Expected Result:** Drag-and-drop works smoothly, visual feedback is clear

- [ ] **Test Case:** Drag and drop valid video file
  - **Steps:** Same as above with video file
  - **Expected Result:** Video drag-and-drop works correctly

### 3.2 Drag-and-Drop Validation
- [ ] **Test Case:** Drag and drop invalid file type
  - **Steps:**
    1. Drag an unsupported file type over drop zone
    2. Drop the file
    3. Verify error message appears
    4. Verify file is not processed
  - **Expected Result:** Error message appears, file is rejected

- [ ] **Test Case:** Drag and drop oversized file
  - **Steps:**
    1. Drag a file larger than allowed size
    2. Drop the file
    3. Verify error message appears
  - **Expected Result:** Size validation error appears

- [ ] **Test Case:** Drag and drop multiple files
  - **Steps:**
    1. Drag multiple files over drop zone
    2. Drop the files
    3. Verify error message appears
  - **Expected Result:** Error message: "Please drop only one file at a time."

### 3.3 Visual Feedback
- [ ] **Test Case:** Drag enter/leave visual feedback
  - **Steps:**
    1. Drag file over drop zone
    2. Verify drop zone highlights
    3. Drag file away from drop zone
    4. Verify highlight is removed
  - **Expected Result:** Visual feedback is clear and responsive

---

## 4. Preview Functionality Testing

### 4.1 Image Preview
- [ ] **Test Case:** Image preview displays correctly
  - **Steps:**
    1. Select an image file
    2. Verify image preview appears
    3. Verify file info (name, size, type) displays
    4. Verify image is properly scaled
  - **Expected Result:** Preview is clear and properly formatted

### 4.2 Video Preview
- [ ] **Test Case:** Video preview displays correctly
  - **Steps:**
    1. Select a video file
    2. Verify video preview appears with controls
    3. Verify video can be played
    4. Verify file info displays
  - **Expected Result:** Video preview works with play controls

### 4.3 Remove Preview
- [ ] **Test Case:** Remove button clears preview
  - **Steps:**
    1. Select a file and verify preview
    2. Click "Remove" button
    3. Verify preview is cleared
    4. Verify drop zone reappears
    5. Verify upload button is disabled
  - **Expected Result:** Preview is cleared, form resets

---

## 5. Upload Progress Testing

### 5.1 Progress Bar
- [ ] **Test Case:** Progress bar updates during upload
  - **Steps:**
    1. Select a file and click upload
    2. Verify progress bar appears
    3. Verify progress percentage updates
    4. Verify progress bar fills as upload progresses
  - **Expected Result:** Progress bar accurately reflects upload progress

### 5.2 Upload States
- [ ] **Test Case:** Upload button states
  - **Steps:**
    1. Verify upload button is disabled when no file selected
    2. Verify upload button is enabled when file selected
    3. Verify upload button is disabled during upload
    4. Verify upload button is re-enabled after upload completes
  - **Expected Result:** Button states are correct at all times

---

## 6. Evidence Display Testing

### 6.1 Match Detail Page
- [ ] **Test Case:** Evidence displays on match detail page
  - **Steps:**
    1. Upload evidence for a match
    2. Navigate to match detail page
    3. Verify evidence gallery section appears
    4. Verify uploaded evidence displays correctly
    5. Verify evidence metadata (uploader, timestamp, description) displays
  - **Expected Result:** Evidence displays correctly with all metadata

- [ ] **Test Case:** Multiple evidence files display
  - **Steps:**
    1. Upload multiple evidence files for same match
    2. Verify all evidence displays in gallery
    3. Verify evidence is ordered by upload time (newest first)
  - **Expected Result:** All evidence files display correctly

### 6.2 Evidence Gallery Page
- [ ] **Test Case:** Navigate to evidence gallery
  - **Steps:**
    1. Click "View All Evidence" link
    2. Verify gallery page loads
    3. Verify all evidence for match displays
    4. Verify images and videos are separated
  - **Expected Result:** Gallery page displays all evidence correctly

- [ ] **Test Case:** Lightbox functionality
  - **Steps:**
    1. Click on an image in the gallery
    2. Verify lightbox opens
    3. Verify full-size image displays
    4. Verify close button works
  - **Expected Result:** Lightbox works correctly

### 6.3 Dispute Evidence Display
- [ ] **Test Case:** Evidence displays in dispute detail page
  - **Steps:**
    1. Create a dispute for a match with evidence
    2. Navigate to dispute detail page (as support staff)
    3. Verify evidence comparison view appears
    4. Verify creator's evidence displays on left
    5. Verify joiner's evidence displays on right
    6. Verify download buttons work
  - **Expected Result:** Evidence displays correctly in dispute view

---

## 7. Access Control Testing

### 7.1 Upload Permissions
- [ ] **Test Case:** Only match participants can upload
  - **Steps:**
    1. Log in as user not in match
    2. Navigate to match detail page
    3. Verify upload section does not appear
  - **Expected Result:** Upload section is hidden for non-participants

- [ ] **Test Case:** Upload only for 'JOINED' matches
  - **Steps:**
    1. Navigate to match detail page for match with status other than 'JOINED'
    2. Verify upload section does not appear
  - **Expected Result:** Upload section only appears for 'JOINED' matches

### 7.2 View Permissions
- [ ] **Test Case:** Only match participants can view evidence
  - **Steps:**
    1. Log in as user not in match
    2. Try to access evidence gallery URL directly
    3. Verify access is denied or redirected
  - **Expected Result:** Non-participants cannot view evidence

---

## 8. Error Handling Testing

### 8.1 Network Errors
- [ ] **Test Case:** Handle network timeout
  - **Steps:**
    1. Disconnect network during upload
    2. Verify error message appears
    3. Verify upload can be retried
  - **Expected Result:** Network errors are handled gracefully

### 8.2 Server Errors
- [ ] **Test Case:** Handle server error (500)
  - **Steps:**
    1. Cause server error (e.g., database issue)
    2. Try to upload evidence
    3. Verify error message appears
  - **Expected Result:** Server errors are handled with user-friendly message

### 8.3 Validation Errors
- [ ] **Test Case:** Server-side validation errors
  - **Steps:**
    1. Bypass client-side validation (if possible)
    2. Upload invalid file
    3. Verify server rejects file
    4. Verify error message appears
  - **Expected Result:** Server-side validation catches invalid files

---

## 9. Mobile Responsiveness Testing

### 9.1 Mobile Layout
- [ ] **Test Case:** Upload UI on mobile device
  - **Steps:**
    1. Open match detail page on mobile device
    2. Verify upload section displays correctly
    3. Verify drag-and-drop zone is appropriately sized
    4. Verify buttons are full-width
    5. Verify preview displays correctly
  - **Expected Result:** UI is mobile-friendly

### 9.2 Mobile Touch Interactions
- [ ] **Test Case:** File selection on mobile
  - **Steps:**
    1. Tap "Choose File" button on mobile
    2. Select file from device
    3. Verify preview appears
    4. Verify upload works
  - **Expected Result:** File selection works on mobile

---

## 10. Browser Compatibility Testing

### 10.1 Chrome
- [ ] **Test Case:** All functionality works in Chrome
  - **Steps:** Test all features in Chrome browser
  - **Expected Result:** All features work correctly

### 10.2 Firefox
- [ ] **Test Case:** All functionality works in Firefox
  - **Steps:** Test all features in Firefox browser
  - **Expected Result:** All features work correctly

### 10.3 Safari
- [ ] **Test Case:** All functionality works in Safari
  - **Steps:** Test all features in Safari browser
  - **Expected Result:** All features work correctly

### 10.4 Edge
- [ ] **Test Case:** All functionality works in Edge
  - **Steps:** Test all features in Edge browser
  - **Expected Result:** All features work correctly

---

## 11. Data Integrity Testing

### 11.1 Evidence Linking
- [ ] **Test Case:** Evidence linked to correct match
  - **Steps:**
    1. Upload evidence for Match A
    2. Upload evidence for Match B
    3. Verify Match A evidence only appears on Match A detail page
    4. Verify Match B evidence only appears on Match B detail page
  - **Expected Result:** Evidence is correctly linked to matches

- [ ] **Test Case:** Evidence linked to correct user
  - **Steps:**
    1. Upload evidence as User A
    2. Upload evidence as User B (same match)
    3. Verify uploader information is correct for each evidence
  - **Expected Result:** Evidence is correctly linked to uploader

### 11.2 Database Integrity
- [ ] **Test Case:** Evidence records created correctly
  - **Steps:**
    1. Upload evidence
    2. Check database records
    3. Verify all fields are populated correctly
    4. Verify file path is correct
  - **Expected Result:** Database records are correct

---

## 12. Performance Testing

### 12.1 Large File Upload
- [ ] **Test Case:** Upload large video file (near 50MB limit)
  - **Steps:**
    1. Upload a video file close to 50MB
    2. Verify upload completes successfully
    3. Verify progress bar updates correctly
    4. Verify file is accessible after upload
  - **Expected Result:** Large files upload successfully

### 12.2 Multiple Uploads
- [ ] **Test Case:** Upload multiple files sequentially
  - **Steps:**
    1. Upload first evidence file
    2. Wait for completion
    3. Upload second evidence file
    4. Verify both files are stored correctly
  - **Expected Result:** Multiple uploads work correctly

---

## 13. Rate Limiting Testing

### 13.1 Upload Rate Limit
- [ ] **Test Case:** Rate limiting enforced (10 uploads per hour)
  - **Steps:**
    1. Upload 10 evidence files within an hour
    2. Try to upload 11th file
    3. Verify rate limit error appears
  - **Expected Result:** Rate limiting prevents excessive uploads

---

## 14. Security Testing

### 14.1 File Path Traversal
- [ ] **Test Case:** Prevent path traversal attacks
  - **Steps:**
    1. Try to upload file with malicious path in filename
    2. Verify file is stored safely
    3. Verify path traversal is prevented
  - **Expected Result:** Path traversal attacks are prevented

### 14.2 CSRF Protection
- [ ] **Test Case:** CSRF token required
  - **Steps:**
    1. Try to upload without CSRF token
    2. Verify request is rejected
  - **Expected Result:** CSRF protection is working

---

## Test Results Summary

### Test Execution
- **Date:** _______________
- **Tester:** _______________
- **Environment:** Development / Staging / Production

### Results
- **Total Test Cases:** 50+
- **Passed:** _______
- **Failed:** _______
- **Blocked:** _______

### Critical Issues
1. ________________________________
2. ________________________________
3. ________________________________

### Minor Issues
1. ________________________________
2. ________________________________
3. ________________________________

### Notes
________________________________
________________________________
________________________________

---

## Sign-off

- **Tested By:** _______________
- **Date:** _______________
- **Status:** ☐ Pass  ☐ Fail  ☐ Needs Rework
- **Approved By:** _______________
- **Date:** _______________



















