// Bootstrap client-side validation for any form with class "needs-validation"
(function () {
  'use strict';
  const forms = document.querySelectorAll('.needs-validation');
  Array.from(forms).forEach(function (form) {
    form.addEventListener('submit', function (event) {
      if (!form.checkValidity()) {
        event.preventDefault();
        event.stopPropagation();
      }
      form.classList.add('was-validated');
    }, false);
  });
})();

// Confirm password match check (registration / profile forms)
function validatePasswordMatch(pwId, confirmId, msgId) {
  const pw = document.getElementById(pwId);
  const confirm = document.getElementById(confirmId);
  const msg = document.getElementById(msgId);
  if (!pw || !confirm) return;

  function check() {
    if (confirm.value && pw.value !== confirm.value) {
      confirm.setCustomValidity('Passwords do not match');
      if (msg) msg.classList.remove('d-none');
    } else {
      confirm.setCustomValidity('');
      if (msg) msg.classList.add('d-none');
    }
  }
  pw.addEventListener('input', check);
  confirm.addEventListener('input', check);
}

// Generic confirm-dialog for destructive actions (delete, blacklist, cancel booking)
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('[data-confirm]').forEach(function (el) {
    el.addEventListener('submit', function (e) {
      const message = el.getAttribute('data-confirm') || 'Are you sure?';
      if (!confirm(message)) {
        e.preventDefault();
      }
    });
  });
});
