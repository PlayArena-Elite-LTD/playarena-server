# Day 13: Reconciliation System - Progress Guide

## Overview
Day 13 focuses on reconciling wallet balances against the transaction ledger to detect and fix discrepancies. This guide will track progress, implementation notes, and testing for each task.

---

## Progress Status

### ✅ Completed Tasks

_(None yet — Day 13 just started.)_

---

## Remaining Tasks

### Task 1: Create reconciliation job/management command
**Status**: ⏳ Pending  
**Description**: Build a Django management command to reconcile wallets in batch.  
**Files to Create/Modify**:
- `wallet/management/commands/reconcile_wallets.py`
- `wallet/models.py` (reuse existing integrity helpers)

**Implementation Notes**:
- Use `Wallet.verify_balance_integrity()` and `Wallet.recalculate_balance()`
- Support `--dry-run` to report without changes
- Support `--limit` and/or `--user-id` for targeted runs

---

### Task 2: Implement wallet balance verification (sum of transactions = balance)
**Status**: ✅ Already implemented  
**Location**: `wallet/models.py`  
**Notes**:
- `verify_balance_integrity()` already calculates expected balance from transactions.
- `recalculate_balance()` already fixes discrepancies.

---

### Task 3: Add automatic discrepancy detection
**Status**: ✅ Already implemented  
**Location**: `wallet/models.py`  
**Notes**:
- `find_wallets_with_discrepancies()` returns wallets where balance ≠ transaction sum.

---

### Task 4: Create reconciliation report
**Status**: ⏳ Pending  
**Description**: Generate summary of discrepancies, counts, and totals.  
**Implementation Notes**:
- Report should include wallet ID, user, expected vs actual balance, discrepancy.
- Output to console (management command) and/or log file.

---

### Task 5: Add manual reconciliation interface for admins
**Status**: ⏳ Pending  
**Description**: Admin view to inspect and optionally fix discrepancies.  
**Files to Modify**:
- `wallet/admin.py`

**Implementation Notes**:
- Add admin action for reconciliation
- Display discrepancy info in admin

---

### Task 6: Set up scheduled reconciliation (daily cron job)
**Status**: ⏳ Pending  
**Description**: Schedule reconciliation job daily.  
**Notes**:
- Use system cron, Celery beat, or scheduled task
- At minimum: document a cron example

**Proposed cron example**:
```
0 2 * * * /path/to/venv/bin/python /path/to/Arena2/manage.py reconcile_wallets --dry-run >> /path/to/Arena2/logs/reconcile.log 2>&1
```

**Production suggestion**:
- Run dry-run daily and alert on discrepancies.
- Run a fixed reconciliation weekly or on demand after review.

---

### Task 7: Add reconciliation alerts for discrepancies
**Status**: ⏳ Pending  
**Description**: Notify admins when discrepancies are found.  
**Implementation Notes**:
- Use logging/email (AdminEmailHandler)
- Optional: create `Notification` for support staff

---

### Task 8: Test reconciliation with various scenarios
**Status**: ⏳ Pending  
**Description**: Add tests for clean wallets and discrepancy cases.  
**Files to Add**:
- `wallet/tests/test_reconciliation.py`

---

## Commit Pattern

Each task should be committed separately using the same format as Day 11:

```
<Short summary line>

<Single paragraph explaining what was done, why, and key details.>
```

---

## Notes

- Wallet integrity helpers already exist in `wallet/models.py`.
- Audit logging is already available and can be used to log reconciliation actions.
- Reconciliation should be safe and idempotent.

