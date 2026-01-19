/**
 * Password Strength Indicator
 * Provides visual feedback on password strength as user types
 */

(function() {
    'use strict';

    // Password strength levels
    const STRENGTH_LEVELS = {
        WEAK: { text: 'Weak', class: 'weak', score: 1 },
        FAIR: { text: 'Fair', class: 'fair', score: 2 },
        GOOD: { text: 'Good', class: 'good', score: 3 },
        STRONG: { text: 'Strong', class: 'strong', score: 4 }
    };

    /**
     * Calculate password strength score
     * @param {string} password - The password to check
     * @returns {number} Strength score (0-4)
     */
    function calculateStrength(password) {
        let score = 0;
        
        if (!password) return 0;
        
        // Length checks
        if (password.length >= 10) score += 1;
        if (password.length >= 12) score += 1;
        if (password.length >= 16) score += 1;
        
        // Character variety checks
        if (/[a-z]/.test(password)) score += 0.5;
        if (/[A-Z]/.test(password)) score += 0.5;
        if (/[0-9]/.test(password)) score += 0.5;
        if (/[^a-zA-Z0-9]/.test(password)) score += 0.5;
        
        // Round to integer
        score = Math.min(Math.floor(score), 4);
        
        return score;
    }

    /**
     * Get strength level from score
     * @param {number} score - Password strength score
     * @returns {Object} Strength level object
     */
    function getStrengthLevel(score) {
        if (score <= 1) return STRENGTH_LEVELS.WEAK;
        if (score === 2) return STRENGTH_LEVELS.FAIR;
        if (score === 3) return STRENGTH_LEVELS.GOOD;
        return STRENGTH_LEVELS.STRONG;
    }

    /**
     * Initialize password strength indicator
     */
    function initPasswordStrength() {
        // Find password field (Django forms typically name it 'password1')
        const passwordInput = document.querySelector('input[name="password1"]');
        const passwordConfirmInput = document.querySelector('input[name="password2"]');
        
        if (!passwordInput) return;

        // Create strength indicator container
        const indicatorContainer = document.createElement('div');
        indicatorContainer.className = 'password-strength-container';
        indicatorContainer.innerHTML = `
            <div class="password-strength-meter">
                <div class="password-strength-bar" id="strengthBar"></div>
            </div>
            <div class="password-strength-text" id="strengthText"></div>
            <div class="password-requirements" id="passwordRequirements">
                <small>Password must be at least 10 characters long</small>
            </div>
        `;

        // Insert after password input field
        const passwordField = passwordInput.closest('p');
        if (passwordField) {
            passwordField.appendChild(indicatorContainer);
        }

        const strengthBar = document.getElementById('strengthBar');
        const strengthText = document.getElementById('strengthText');
        const requirementsDiv = document.getElementById('passwordRequirements');

        /**
         * Update password strength indicator
         */
        function updateStrength() {
            const password = passwordInput.value;
            const score = calculateStrength(password);
            const level = getStrengthLevel(score);

            // Update strength bar
            strengthBar.className = 'password-strength-bar ' + level.class;
            strengthBar.style.width = (score * 25) + '%';

            // Update strength text
            if (password.length === 0) {
                strengthText.textContent = '';
                strengthText.className = 'password-strength-text';
            } else {
                strengthText.textContent = level.text;
                strengthText.className = 'password-strength-text ' + level.class;
            }

            // Update requirements
            const requirements = [];
            if (password.length < 10) {
                requirements.push('At least 10 characters');
            }
            if (!/[a-z]/.test(password)) {
                requirements.push('Lowercase letter');
            }
            if (!/[A-Z]/.test(password)) {
                requirements.push('Uppercase letter');
            }
            if (!/[0-9]/.test(password)) {
                requirements.push('Number');
            }
            if (!/[^a-zA-Z0-9]/.test(password)) {
                requirements.push('Special character');
            }

            if (requirements.length > 0 && password.length > 0) {
                requirementsDiv.innerHTML = '<small>Still need: ' + requirements.join(', ') + '</small>';
            } else if (password.length > 0) {
                requirementsDiv.innerHTML = '<small class="requirements-met">✓ All requirements met</small>';
            } else {
                requirementsDiv.innerHTML = '<small>Password must be at least 10 characters long</small>';
            }

            // Check password confirmation match
            if (passwordConfirmInput && passwordConfirmInput.value) {
                checkPasswordMatch();
            }
        }

        /**
         * Check if password and confirmation match
         */
        function checkPasswordMatch() {
            if (!passwordConfirmInput) return;

            const password = passwordInput.value;
            const confirmPassword = passwordConfirmInput.value;

            const confirmField = passwordConfirmInput.closest('p');
            if (!confirmField) return;

            // Remove existing match indicator
            let matchIndicator = confirmField.querySelector('.password-match-indicator');
            if (!matchIndicator) {
                matchIndicator = document.createElement('div');
                matchIndicator.className = 'password-match-indicator';
                confirmField.appendChild(matchIndicator);
            }

            if (confirmPassword.length === 0) {
                matchIndicator.textContent = '';
                matchIndicator.className = 'password-match-indicator';
            } else if (password === confirmPassword) {
                matchIndicator.textContent = '✓ Passwords match';
                matchIndicator.className = 'password-match-indicator match';
            } else {
                matchIndicator.textContent = '✗ Passwords do not match';
                matchIndicator.className = 'password-match-indicator no-match';
            }
        }

        // Add event listeners
        passwordInput.addEventListener('input', updateStrength);
        passwordInput.addEventListener('keyup', updateStrength);
        
        if (passwordConfirmInput) {
            passwordConfirmInput.addEventListener('input', checkPasswordMatch);
            passwordConfirmInput.addEventListener('keyup', checkPasswordMatch);
        }

        // Initial update
        updateStrength();
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initPasswordStrength);
    } else {
        initPasswordStrength();
    }
})();
