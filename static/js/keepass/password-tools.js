(() => {
  "use strict";

  const randInt = (n) => Math.floor(Math.random() * n);

  function shuffle(items) {
    for (let i = items.length - 1; i > 0; i -= 1) {
      const j = randInt(i + 1);
      [items[i], items[j]] = [items[j], items[i]];
    }
    return items;
  }

  function passwordStrengthMsg(password) {
    if (!password || password.length < 8) return "Weak: too short";
    const categories = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^\w]/];
    const categoryCount = categories.filter((pattern) => pattern.test(password)).length;
    if (password.length >= 16 && categoryCount >= 3) return "Strong password";
    return categoryCount >= 3 ? "Okay password" : "Weak: use more variety";
  }

  function generatePassword(length) {
    const pools = [
      "abcdefghjkmnpqrstuvwxyz",
      "ABCDEFGHJKLMNPQRSTUVWXYZ",
      "23456789",
      "!@#$%^&*()_+-=",
    ];
    const result = pools.map((pool) => pool[randInt(pool.length)]);
    const all = pools.join("");
    while (result.length < length) result.push(all[randInt(all.length)]);
    return shuffle(result).join("");
  }

  function init() {
    const generateButton = document.getElementById("kp-smb-gen");
    const copyButton = document.getElementById("kp-smb-copy");
    const toggleButton = document.getElementById("kp-smb-toggle");
    const lengthSelect = document.getElementById("kp-smb-len");
    const passwordInput = document.getElementById("kp-smb-pass");
    const confirmInput = document.getElementById("kp-smb-pass2");
    const hint = document.getElementById("kp-smb-hint");

    if (generateButton) {
      generateButton.onclick = () => {
        let length = Number.parseInt(lengthSelect?.value || "16", 10);
        if (!Number.isFinite(length)) length = 16;
        length = Math.max(8, Math.min(64, length));
        const value = generatePassword(length);
        if (passwordInput) passwordInput.value = value;
        if (confirmInput) confirmInput.value = value;
        if (hint) hint.textContent = passwordStrengthMsg(value);
      };
    }

    if (copyButton) {
      copyButton.onclick = async () => {
        const value = (passwordInput?.value || "").trim();
        if (!value) return;
        try { await navigator.clipboard.writeText(value); } catch {}
      };
    }

    if (toggleButton) {
      toggleButton.onclick = () => {
        const isShown = passwordInput?.type === "text";
        if (passwordInput) passwordInput.type = isShown ? "password" : "text";
        if (confirmInput) confirmInput.type = isShown ? "password" : "text";
        toggleButton.textContent = isShown ? "Show" : "Hide";
      };
    }
  }

  window.KeepassPasswordTools = { init, passwordStrengthMsg };
})();
