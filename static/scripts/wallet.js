// Wallet form validation and processing
document.addEventListener('DOMContentLoaded', function() {
    const depositForm = document.querySelector('form[action*="deposit"]');
    const withdrawForm = document.querySelector('form[action*="withdraw"]');
    
    // Deposit form validation
    if (depositForm) {
        const amountInput = depositForm.querySelector('input[name="amount"]');
        const submitButton = depositForm.querySelector('button[type="submit"]');
        
        depositForm.addEventListener('submit', function(e) {
            const amount = parseFloat(amountInput.value);
            
            // Client-side validation
            if (isNaN(amount) || amount <= 0) {
                e.preventDefault();
                alert('Please enter a valid amount greater than $0.00');
                amountInput.focus();
                return false;
            }
            
            if (amount < 1.00) {
                e.preventDefault();
                alert('Minimum deposit amount is $1.00');
                amountInput.focus();
                return false;
            }
            
            if (amount > 10000.00) {
                e.preventDefault();
                alert('Maximum deposit amount is $10,000.00');
                amountInput.focus();
                return false;
            }
            
            // Show loading state
            submitButton.disabled = true;
            submitButton.textContent = 'Processing...';
        });
        
        // Real-time amount validation
        amountInput.addEventListener('input', function() {
            const amount = parseFloat(this.value);
            if (!isNaN(amount)) {
                if (amount < 1.00) {
                    this.setCustomValidity('Minimum deposit amount is $1.00');
                } else if (amount > 10000.00) {
                    this.setCustomValidity('Maximum deposit amount is $10,000.00');
                } else {
                    this.setCustomValidity('');
                }
            }
        });
    }
    
    // Withdrawal form validation
    if (withdrawForm) {
        const amountInput = withdrawForm.querySelector('input[name="amount"]');
        const accountDetailsInput = withdrawForm.querySelector('textarea[name="account_details"]');
        const submitButton = withdrawForm.querySelector('button[type="submit"]');
        
        withdrawForm.addEventListener('submit', function(e) {
            const amount = parseFloat(amountInput.value);
            const accountDetails = accountDetailsInput.value.trim();
            
            // Client-side validation
            if (isNaN(amount) || amount <= 0) {
                e.preventDefault();
                alert('Please enter a valid amount greater than $0.00');
                amountInput.focus();
                return false;
            }
            
            if (amount < 1.00) {
                e.preventDefault();
                alert('Minimum withdrawal amount is $1.00');
                amountInput.focus();
                return false;
            }
            
            if (accountDetails.length < 5) {
                e.preventDefault();
                alert('Please provide valid account details (at least 5 characters)');
                accountDetailsInput.focus();
                return false;
            }
            
            // Show loading state
            submitButton.disabled = true;
            submitButton.textContent = 'Processing...';
        });
        
        // Real-time amount validation
        amountInput.addEventListener('input', function() {
            const amount = parseFloat(this.value);
            if (!isNaN(amount) && amount < 1.00) {
                this.setCustomValidity('Minimum withdrawal amount is $1.00');
            } else {
                this.setCustomValidity('');
            }
        });
        
        // Real-time account details validation
        accountDetailsInput.addEventListener('input', function() {
            if (this.value.trim().length < 5 && this.value.trim().length > 0) {
                this.setCustomValidity('Account details must be at least 5 characters');
            } else {
                this.setCustomValidity('');
            }
        });
    }
});
