# Day 25 - Security Audit & Penetration Testing

Goal: Identify and fix security weaknesses across auth, payments, uploads, and admin access.

## 1) Authentication & Session Security
- [ ] Verify secure session cookies (HttpOnly, Secure in prod)
- [ ] Confirm session expiration behavior
- [ ] Test login brute-force protections (rate limiting)
- [ ] Test lockout/slowdown behavior after repeated failures
- [ ] Ensure inactive users cannot authenticate
- [ ] Verify logout clears session tokens

## 2) Authorization & Access Control
- [ ] Ensure non-auth users cannot access protected pages
- [ ] Verify staff-only routes blocked for non-staff
- [ ] Verify superuser-only actions blocked for staff
- [ ] Confirm object-level permissions (wallet, matches, disputes)
- [ ] Test IDOR attempts on user, wallet, and match endpoints

## 3) CSRF & XSS
- [ ] Verify CSRF protection on all forms
- [ ] Confirm CSRF token required on POST/PUT/PATCH/DELETE
- [ ] Test reflected XSS in search/filter/query params
- [ ] Test stored XSS in user profile fields and messages
- [ ] Validate rich text inputs are sanitized

## 4) SQL Injection & Input Validation
- [ ] Attempt SQL injection on login, search, filters
- [ ] Validate all inputs are sanitized at form/serializer level
- [ ] Ensure raw SQL not used without parameterization

## 5) File Upload Security (Evidence)
- [ ] Verify file type validation (MIME + extension)
- [ ] Ensure oversized files are rejected
- [ ] Confirm file paths are not user-controllable
- [ ] Verify uploads are not executable
- [ ] Ensure evidence access is restricted

## 6) Payment Security
- [ ] Verify webhook signature validation
- [ ] Test replayed webhooks are rejected
- [ ] Ensure payment references are unique
- [ ] Verify duplicate deposits are prevented
- [ ] Confirm failure states do not credit wallets

## 7) Rate Limiting & Abuse
- [ ] Rate limit login, signup, password reset
- [ ] Rate limit deposit/withdraw actions
- [ ] Rate limit evidence uploads
- [ ] Rate limit messaging endpoints

## 8) Headers & Transport Security
- [ ] Confirm HSTS enabled in production
- [ ] Confirm X-Frame-Options set to DENY
- [ ] Confirm Content-Security-Policy enforced
- [ ] Confirm Secure/HttpOnly cookies in production

## 9) API Security
- [ ] JWT tokens required for protected endpoints
- [ ] Ensure refresh token flow is safe
- [ ] Validate token expiration handling
- [ ] Confirm permissions enforce user isolation

## 10) Admin Hardening
- [ ] Admin URLs not accessible to non-staff
- [ ] Admin actions logged (audit)
- [ ] Admin pages not leaking sensitive info
- [ ] Admin password reset flow secured
