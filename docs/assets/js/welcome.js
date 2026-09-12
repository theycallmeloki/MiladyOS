// Downloads and navigation work without JavaScript. Clipboard is an enhancement.
if (navigator.clipboard && window.isSecureContext) {
  document.querySelectorAll('[data-copy]').forEach((button) => {
    button.hidden = false;
    button.addEventListener('click', async () => {
      const status = button.nextElementSibling;
      try {
        await navigator.clipboard.writeText(document.getElementById(button.dataset.copy).textContent.trim());
        status.textContent = 'Copied.';
      } catch {
        status.textContent = 'Select the checksum above to copy it manually.';
      }
    });
  });
}
