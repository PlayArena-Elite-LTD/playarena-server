# Manual Test Checklist (Comprehensive)

Use this for full end-to-end and exploratory testing before release.

## 1) Environment & Smoke Tests
- [ ] Server starts without errors
- [ ] Admin loads at `/admin/`
- [ ] Home/landing page loads
- [ ] Static assets (CSS/JS/images) load without 404s
- [ ] Media uploads are served correctly
- [ ] Email sending works in current environment

## 2) Authentication & Accounts
- [ ] Sign up with valid details
- [ ] Sign up with existing email (error shown)
- [ ] Sign up with weak password (blocked)
- [ ] Login with valid credentials
- [ ] Login with invalid credentials
- [ ] Logout redirects correctly
- [ ] Password change (while logged in)
- [ ] Password reset request (email delivered)
- [ ] Password reset link works and expires properly
- [ ] Account inactive / disabled user cannot login

## 3) Profile & Settings
- [ ] View profile page
- [ ] Edit profile fields and save
- [ ] Validation errors shown for invalid data
- [ ] Profile changes persist after refresh
- [ ] Avatar / image upload (if enabled)

## 4) Dashboard
- [ ] Dashboard loads for authenticated user
- [ ] Wallet KPI values display correctly
- [ ] Recent transactions list renders correctly
- [ ] Dashboard links navigate correctly
- [ ] Empty state (no transactions) shows cleanly

## 5) Wallet - Deposit
- [ ] Open deposit page
- [ ] Deposit amount validation (min/max)
- [ ] Payment method selection works
- [ ] Successful deposit updates balance
- [ ] Failed deposit shows error message
- [ ] Deposit status appears in transactions
- [ ] Duplicate/rapid submissions handled

## 6) Wallet - Withdrawal
- [ ] Open withdrawal page
- [ ] Withdrawal amount validation (min/max/available balance)
- [ ] Account details required when not using saved method
- [ ] Successful withdrawal updates balance
- [ ] Failed withdrawal shows error message
- [ ] Withdrawal status appears in transactions
- [ ] Withdrawal retry/queue behavior (if enabled)

## 7) Wallet - Transactions
- [ ] Transactions page loads
- [ ] Filters/sorting (if available)
- [ ] Credit/debit formatting correct
- [ ] Empty state displays cleanly

## 8) Payment Methods
- [ ] Add a payment method
- [ ] Edit a payment method
- [ ] Set default payment method
- [ ] Delete a payment method
- [ ] Validation for invalid/missing details

## 9) Matches - Create & Join
- [ ] Create match (valid)
- [ ] Create match with invalid amount/game/device
- [ ] Join match with valid code
- [ ] Join match with invalid/expired code
- [ ] Cannot join own match (if restricted)
- [ ] Match status updates to JOINED
- [ ] Match list reflects new match

## 10) Match Results & Evidence
- [ ] Submit result (creator)
- [ ] Submit result (joiner)
- [ ] Draw flow works as expected
- [ ] Evidence upload (image)
- [ ] Evidence upload (video)
- [ ] Invalid file type blocked
- [ ] Oversized file blocked
- [ ] Evidence gallery view loads
- [ ] Evidence download works
- [ ] Evidence delete (if allowed)

## 11) Disputes
- [ ] Dispute creation triggers correctly
- [ ] Dispute appears in support panel
- [ ] Assign dispute to support staff
- [ ] Evidence is visible in dispute detail
- [ ] Add staff notes to evidence
- [ ] Resolve dispute and credit winner
- [ ] Escalate dispute
- [ ] Suspend user from dispute panel

## 12) Messaging & Notifications
- [ ] Send message to another user
- [ ] View conversation history
- [ ] Unread count updates
- [ ] Notifications list loads (if used)

## 13) Admin - Access & Dashboard
- [ ] Admin login works
- [ ] Admin sidebar toggle works (closed by default)
- [ ] Admin dashboard cards load
- [ ] KPI values update (live users, total users, environment)
- [ ] App cards and model links work

## 14) Admin - Wallet Operations
- [ ] Deposit list loads in admin
- [ ] Withdrawal list loads in admin
- [ ] Deposit status updates via admin
- [ ] Withdrawal status updates via admin
- [ ] Reconciliation action runs without errors

## 15) Security & Abuse Checks
- [ ] Rate limiting triggers for auth abuse
- [ ] CSRF protection enforced on forms
- [ ] Unauthorized users blocked from protected pages
- [ ] Staff-only/admin-only routes protected
- [ ] Evidence access restricted to allowed users

## 16) API (if used)
- [ ] Obtain JWT token
- [ ] Access `/api/me/` with token
- [ ] Wallet API endpoints return correct data
- [ ] Match API endpoints work end-to-end
- [ ] Permissions enforce user isolation
- [ ] Rate limit rules apply (if configured)

## 17) Cross-Browser & Responsiveness
- [ ] Mobile layout for auth pages
- [ ] Mobile layout for dashboard/wallet
- [ ] Mobile layout for match flows
- [ ] Tested on Chrome, Firefox, Safari/Edge

## 18) Performance & Reliability
- [ ] Page load times acceptable
- [ ] No 500 errors in common flows
- [ ] Logging captures critical actions
- [ ] Retry logic for payment failures

## 19) Production Readiness
- [ ] DEBUG disabled in production
- [ ] Secrets loaded from environment
- [ ] Static files served correctly
- [ ] Media storage configured (S3/Cloudinary if used)
- [ ] HTTPS enforced
