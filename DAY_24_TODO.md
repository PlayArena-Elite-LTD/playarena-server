# Day 24 - Payment Integration Testing

Goal: Validate end-to-end payment flows (deposit/withdrawal) with security checks, webhooks, and failure handling.

## 1) Environment & Configuration
- [ ] Confirm gateway API keys are loaded from env (no hardcoded secrets)
- [ ] Confirm test/sandbox mode enabled in non-production
- [ ] Verify webhook endpoint URLs are configured
- [ ] Check webhook secrets set for signature verification
- [ ] Ensure test webhooks can reach the server (tunnel if local)

## 2) Deposit Flow (Happy Path)
- [ ] Create deposit via UI
- [ ] Confirm gateway initializes deposit successfully
- [ ] Verify redirect/payment URL opens correctly
- [ ] Complete payment in sandbox
- [ ] Verify webhook marks deposit as COMPLETED
- [ ] Wallet balance increases correctly
- [ ] Transaction record created with correct metadata

## 3) Deposit Flow (Failure Path)
- [ ] Simulate payment failure in sandbox
- [ ] Verify deposit status becomes FAILED
- [ ] User sees clear error message
- [ ] Ensure wallet balance unchanged
- [ ] Audit log created for failure

## 4) Duplicate & Replay Protection
- [ ] Replay same webhook event → no double credit
- [ ] Duplicate payment reference rejected
- [ ] Duplicate transaction ID rejected

## 5) Withdrawal Flow (Happy Path)
- [ ] Create withdrawal via UI
- [ ] Verify withdrawal status transitions to PROCESSING
- [ ] Gateway processes payout (sandbox/manual)
- [ ] Webhook marks withdrawal as COMPLETED
- [ ] Wallet balance decreases correctly
- [ ] Transaction record created with correct metadata

## 6) Withdrawal Flow (Failure Path)
- [ ] Simulate payout failure
- [ ] Verify status becomes FAILED and failure reason stored
- [ ] Wallet balance is not double-debited
- [ ] Audit log created for failure

## 7) Manual/Bank Transfer Flow
- [ ] Create bank transfer withdrawal
- [ ] Ensure status is PENDING/PROCESSING (manual)
- [ ] Admin can approve/complete manually
- [ ] Manual completion updates wallet and logs

## 8) Admin Controls
- [ ] Admin can view deposits/withdrawals lists
- [ ] Admin can update status without breaking rules
- [ ] Admin bulk actions behave correctly

## 9) Edge Cases
- [ ] Large deposit blocked over max limit
- [ ] Small deposit blocked under min limit
- [ ] Withdrawal blocked when insufficient balance
- [ ] Multi-currency (if supported) handled correctly
- [ ] Timeouts handled with retry or clear message

## 10) Security Verification
- [ ] Webhook signature verification enforced
- [ ] Reject invalid signatures
- [ ] IP address and user agent stored for deposits
- [ ] Gateway response stored (audit/debug)
- [ ] Rate limits prevent abuse on deposit/withdraw endpoints
