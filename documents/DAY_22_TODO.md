# Day 22 - Comprehensive Testing (Backend)

Goal: Achieve strong automated test coverage for core backend workflows with security-focused cases.

## 1) Test Harness & Setup
- [ ] Confirm test database configuration is isolated from production
- [ ] Add a base test mixin for authenticated user + wallet setup
- [ ] Add factories/fixtures for users, wallets, matches, disputes
- [ ] Add test helpers for creating deposits/withdrawals
- [ ] Add helper for evidence file creation (image + video)
- [ ] Add helper for API client auth (JWT)
- [ ] Ensure test cleanup removes uploaded test files

## 2) Wallet Unit Tests
- [ ] Create wallet and verify default balance
- [ ] Test `Wallet.verify_balance_integrity()` on empty wallet
- [ ] Test `Wallet.verify_balance_integrity()` after credits/debits
- [ ] Test `Wallet.recalculate_balance()` updates balance correctly
- [ ] Test negative balance prevention (if applicable)
- [ ] Test rounding/precision for decimal amounts
- [ ] Test transaction ordering and count

## 3) Deposit Flow Tests
- [ ] Deposit creation requires authenticated user
- [ ] Deposit amount validation (min/max, positive)
- [ ] Deposit payment method validation
- [ ] Deposit status transitions (PENDING → PROCESSING → COMPLETED)
- [ ] Prevent invalid status transitions
- [ ] Duplicate transaction ID is rejected
- [ ] Webhook completes deposit and updates wallet
- [ ] Webhook with invalid signature is rejected
- [ ] Audit log created on deposit completion

## 4) Withdrawal Flow Tests
- [ ] Withdrawal creation requires authenticated user
- [ ] Withdrawal amount validation (min/max, balance check)
- [ ] Withdrawal payment method validation
- [ ] Withdrawal status transitions (PENDING → PROCESSING → COMPLETED/FAILED)
- [ ] Prevent invalid status transitions
- [ ] Webhook completes withdrawal and updates wallet
- [ ] Webhook failure updates status + failure reason
- [ ] Audit log created on withdrawal completion/failure

## 5) Match Creation & Joining Tests
- [ ] Create match with valid inputs
- [ ] Create match with invalid game/device/amount fails
- [ ] Joining code is generated and unique
- [ ] Join match with valid code
- [ ] Join match with invalid/expired code fails
- [ ] Prevent creator from joining own match
- [ ] Match status updates to JOINED
- [ ] Wallet is debited/credited appropriately on join (if applicable)
- [ ] Audit log created on match create/join

## 6) Match Result & Dispute Tests
- [ ] Creator submits result (no evidence)
- [ ] Joiner submits result (no evidence)
- [ ] Draw flow handled correctly
- [ ] Dispute auto-created on conflicting results
- [ ] Dispute status changes handled correctly
- [ ] Dispute resolution credits winner correctly
- [ ] Unauthorized user cannot resolve dispute
- [ ] Audit log created for dispute resolution

## 7) Evidence Tests
- [ ] Evidence upload requires match participant
- [ ] Image upload accepted (valid type/size)
- [ ] Video upload accepted (valid type/size)
- [ ] Invalid file type rejected
- [ ] Oversized file rejected
- [ ] Evidence list restricted to match participants/staff
- [ ] Evidence download restricted to match participants/staff
- [ ] Evidence delete only allowed for uploader and active match
- [ ] Staff notes update succeeds for staff only

## 8) Auth & Security Tests
- [ ] Login rate limiting works (if enabled in test env)
- [ ] CSRF protected endpoints reject missing token
- [ ] Permission checks on staff/admin endpoints
- [ ] API JWT auth required for protected endpoints
- [ ] Token refresh works and old token expires
- [ ] Inactive user cannot authenticate

## 9) API Endpoint Tests (Core)
- [ ] `/api/me/` returns correct user
- [ ] Wallet endpoints return user-specific data only
- [ ] Match endpoints enforce permissions
- [ ] Dispute endpoints enforce staff permissions
- [ ] Message endpoints enforce sender/recipient access
- [ ] Notifications endpoints return only user notifications
- [ ] Throttling limits apply (if configured)

## 10) Error Handling & Edge Cases
- [ ] 404s returned for missing resources
- [ ] 403s for unauthorized access
- [ ] 400s for validation errors
- [ ] API errors are consistent and sanitized
- [ ] No stack traces returned to client

## 11) Coverage & Reporting
- [ ] Run test suite with coverage
- [ ] Verify core apps meet target coverage
- [ ] Document any skipped tests + reason

## 12) Security Regression Checklist
- [ ] Ensure no test fixtures include real secrets
- [ ] Verify sensitive fields are not logged in tests
- [ ] Confirm webhook tests include signature validation
