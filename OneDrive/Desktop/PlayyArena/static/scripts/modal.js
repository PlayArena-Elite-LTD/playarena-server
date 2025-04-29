/**
 * Confirmation Modal
 * A reusable modal for confirming user actions
 */
const confirmationModal = {
  modal: null,
  title: null,
  message: null,
  confirmBtn: null,
  onConfirm: null,
  formToSubmit: null,

  init() {
    // Get modal elements
    this.modal = document.getElementById('confirmation-modal');
    this.title = document.getElementById('modal-title');
    this.message = document.getElementById('modal-message');
    this.confirmBtn = document.getElementById('modal-confirm-btn');

    // Set up event listeners
    document.querySelectorAll('[data-action="close-modal"]').forEach(element => {
      element.addEventListener('click', () => this.close());
    });

    // Close on background click
    this.modal.querySelector('.modal-background').addEventListener('click', () => this.close());

    // Close on escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.modal.classList.contains('active')) {
        this.close();
      }
    });

    // Handle confirm button
    this.confirmBtn.addEventListener('click', () => {
      if (this.onConfirm) {
        this.onConfirm();
      } else if (this.formToSubmit) {
        this.formToSubmit.submit();
      }
      this.close();
    });

    // Initialize data-confirm triggers
    this.initTriggers();
  },

  initTriggers() {
    // Set up triggers for forms with data-confirm attribute
    document.querySelectorAll('form[data-confirm]').forEach(form => {
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        this.confirm({
          title: form.getAttribute('data-confirm-title') || 'Confirm Action',
          message: form.getAttribute('data-confirm') || 'Are you sure you want to proceed?',
          confirmText: form.getAttribute('data-confirm-button') || 'Confirm',
          form: form
        });
      });
    });

    // Set up triggers for links and buttons with data-confirm attribute
    document.querySelectorAll('a[data-confirm], button[data-confirm]').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        
        // Get the original action (href for links, form submission for buttons)
        const action = () => {
          if (el.tagName === 'A') {
            window.location.href = el.getAttribute('href');
          } else if (el.type === 'submit' && el.form) {
            el.form.submit();
          }
        };

        this.confirm({
          title: el.getAttribute('data-confirm-title') || 'Confirm Action',
          message: el.getAttribute('data-confirm') || 'Are you sure you want to proceed?',
          confirmText: el.getAttribute('data-confirm-button') || 'Confirm',
          onConfirm: action
        });
      });
    });
  },

  confirm({ title, message, confirmText, onConfirm, form }) {
    // Set content
    this.title.textContent = title || 'Confirmation';
    this.message.textContent = message || 'Are you sure you want to continue?';
    this.confirmBtn.textContent = confirmText || 'Confirm';
    
    // Set action
    this.onConfirm = onConfirm || null;
    this.formToSubmit = form || null;
    
    // Show the modal
    this.open();
  },

  open() {
    this.modal.classList.add('active');
    document.body.style.overflow = 'hidden'; // Prevent background scrolling
  },

  close() {
    this.modal.classList.remove('active');
    document.body.style.overflow = '';
  }
};

// Initialize modal once DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
  confirmationModal.init();
});