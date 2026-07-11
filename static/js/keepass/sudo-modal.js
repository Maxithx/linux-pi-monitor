(() => {
  "use strict";

  function prompt(onComplete) {
    const modal = document.getElementById("kp-sudo-modal");
    const input = document.getElementById("kp-sudo-modal-input");
    const error = document.getElementById("kp-sudo-err");
    const okButton = document.getElementById("kp-sudo-ok");
    const cancelButton = document.getElementById("kp-sudo-cancel");
    const closeButton = document.getElementById("kp-sudo-close");

    if (!modal || !input || !error || !okButton || !cancelButton || !closeButton) {
      throw new Error("KeePass sudo modal markup is incomplete");
    }

    error.style.display = "none";
    modal.style.display = "flex";
    setTimeout(() => {
      try { input.focus(); } catch {}
    }, 10);

    function cleanup() {
      okButton.onclick = null;
      cancelButton.onclick = null;
      closeButton.onclick = null;
    }

    function cancel() {
      cleanup();
      modal.style.display = "none";
      onComplete(null);
    }

    cancelButton.onclick = cancel;
    closeButton.onclick = cancel;
    okButton.onclick = () => {
      const password = (input.value || "").trim();
      if (!password) {
        error.style.display = "block";
        return;
      }
      cleanup();
      modal.style.display = "none";
      onComplete(password);
    };
  }

  window.KeepassSudoModal = { prompt };
})();
