# Day 4: Wallet UI Implementation - Step-by-Step Guide

## Current Status Analysis

✅ **Already Done:**
- URL routes exist (`/wallet/deposit/`, `/wallet/withdraw/`)
- View functions exist but need modification (currently only handle POST)
- Models exist (Wallet, Transaction)
- Rate limiting is implemented

❌ **Needs to be Done:**
- Django forms (deposit/withdraw)
- All wallet templates
- Modify views to handle GET requests
- Update dashboard links

---

## Step-by-Step Implementation Plan

### STEP 1: Create Django Forms (`wallet/forms.py`)

**What to do:**
1. Create `wallet/forms.py` file
2. Create `DepositForm` with:
   - `amount` field (DecimalField, min=1, max=10000)
   - `payment_method` field (ChoiceField with options: Stripe, PayPal, Mobile Money, Bank Transfer, Other)
3. Create `WithdrawalForm` with:
   - `amount` field (DecimalField, min=1, max=5000)
   - `payment_method` field (ChoiceField)
   - `account_details` field (CharField with Textarea widget)

**Files to create:** `wallet/forms.py`

---

### STEP 2: Modify Views (`wallet/views.py`)

**What to do:**
1. Import the forms
2. Modify `deposit` view:
   - Remove `@require_http_methods(["POST"])` decorator
   - Handle GET: Display form
   - Handle POST: Process form data
   - Keep existing validation logic
3. Modify `withdraw` view:
   - Remove `@require_http_methods(["POST"])` decorator  
   - Handle GET: Display form
   - Handle POST: Process form data
   - Keep existing validation logic
4. Add transaction_history view if not exists (for transactions.html)

**Files to modify:** `wallet/views.py`

---

### STEP 3: Create Templates Directory

**What to do:**
1. Create `templates/wallet/` directory

**Command:**
```powershell
mkdir templates\wallet
```

---

### STEP 4: Create `wallet.html` Template

**What to do:**
1. Create `templates/wallet/wallet.html`
2. Extend `base.html`
3. Display:
   - Current balance (from `wallet.balance`)
   - "Add Funds" button linking to deposit page
   - "Withdraw" button linking to withdraw page
   - Recent transactions (last 10-15)
   - Link to full transaction history
4. Use existing dashboard styling (copy from dashboard.html)

**Files to create:** `templates/wallet/wallet.html`

---

### STEP 5: Create `deposit.html` Template

**What to do:**
1. Create `templates/wallet/deposit.html`
2. Extend `base.html`
3. Create form with:
   - CSRF token
   - Amount field
   - Payment method dropdown
   - Submit button
   - Cancel/Back link
4. Display messages (errors/success)
5. Match styling from `create_match.html`

**Files to create:** `templates/wallet/deposit.html`

---

### STEP 6: Create `withdraw.html` Template

**What to do:**
1. Create `templates/wallet/withdraw.html`
2. Extend `base.html`
3. Create form with:
   - CSRF token
   - Amount field
   - Payment method dropdown
   - Account details textarea
   - Current balance display
   - Submit button
   - Cancel/Back link
4. Display messages
5. Match styling from `create_match.html`

**Files to create:** `templates/wallet/withdraw.html`

---

### STEP 7: Create `transactions.html` Template

**What to do:**
1. Create `templates/wallet/transactions.html`
2. Extend `base.html`
3. Display full transaction list (all transactions)
4. Show: type, amount, date, description
5. Match styling from dashboard transaction list
6. Add pagination if many transactions

**Files to create:** `templates/wallet/transactions.html`

---

### STEP 8: Update Dashboard Links

**What to do:**
1. Open `templates/dashboard.html`
2. Find the "Add Funds" button (line 37)
3. Change `href="#"` to `href="{% url 'deposit' %}"`
4. Find the "Withdraw" button (line 38)
5. Change `href="#"` to `href="{% url 'withdraw' %}"`

**Files to modify:** `templates/dashboard.html`

---

### STEP 9: Add Transaction History URL (if needed)

**What to do:**
1. Check if transaction_history view exists
2. If not, add view to `wallet/views.py`
3. Add URL pattern to `wallet/urls.py`: `path('transactions/', views.transaction_history, name='transaction_history')`

**Files to modify:** `wallet/views.py`, `wallet/urls.py`

---

### STEP 10: Testing

**Test each feature:**
1. ✅ Visit `/wallet/` - should show wallet page
2. ✅ Click "Add Funds" - should go to deposit page
3. ✅ Submit deposit form - should create transaction
4. ✅ Click "Withdraw" - should go to withdraw page
5. ✅ Submit withdrawal form - should create transaction
6. ✅ Check transaction history - should show all transactions
7. ✅ Verify form validation works
8. ✅ Verify error messages display
9. ✅ Verify success messages display

---

## Implementation Order (Recommended)

1. **Backend First:**
   - Step 1: Create forms.py
   - Step 2: Modify views.py
   - Step 9: Add transaction history URL (if needed)

2. **Frontend Second:**
   - Step 3: Create templates directory
   - Step 4: Create wallet.html
   - Step 5: Create deposit.html
   - Step 6: Create withdraw.html
   - Step 7: Create transactions.html
   - Step 8: Update dashboard.html

3. **Testing Last:**
   - Step 10: Test everything

---

## Quick Reference: Design Patterns to Follow

**Form Structure (from create_match.html):**
```html
<div class="form-group">
  <label for="{{ form.field.id_for_label }}" class="form-label">{{ form.field.label }}</label>
  {{ form.field }}
  {% if form.field.errors %}
    <div class="form-field-errors">
      {% for error in form.field.errors %}
        <p class="form-field-error">{{ error }}</p>
      {% endfor %}
    </div>
  {% endif %}
</div>
```

**Section Structure:**
```html
<section class="section">
  <div class="container">
    <h2 class="section-title">Title</h2>
    <!-- content -->
  </div>
</section>
```

**Card Structure (from dashboard.html):**
```html
<div class="dashboard-card">
  <div class="dashboard-card-header">
    <h3 class="dashboard-card-title">Title</h3>
  </div>
  <!-- content -->
</div>
```

---

## Estimated Time per Step

- Step 1 (Forms): 30 minutes
- Step 2 (Views): 45 minutes
- Step 3 (Directory): 1 minute
- Step 4 (wallet.html): 1 hour
- Step 5 (deposit.html): 1 hour
- Step 6 (withdraw.html): 1 hour
- Step 7 (transactions.html): 45 minutes
- Step 8 (Dashboard): 5 minutes
- Step 9 (URL): 10 minutes
- Step 10 (Testing): 1 hour

**Total: ~6-7 hours** (matches the estimate!)





