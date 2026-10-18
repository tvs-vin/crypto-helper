// The sign-in box: first-launch setup, password, then 2FA (code or recovery code).
// It sits over the desktop; when it resolves, the caller restores the user's layout.

import { ApiError, api } from "./api.js";
import { brandMark, fill, h } from "./dom.js";

export function showAuth({ mode = "login", reason = null, username = "" } = {}) {
  return new Promise((resolve) => {
    const card = h("div", { class: "auth-card" });
    const overlay = h("div", { class: "overlay", role: "dialog", "aria-modal": "true",
      "aria-labelledby": "auth-title" }, card);
    document.body.append(overlay);

    const notice = (text, kind = "error") => h("div", { class: `notice ${kind}`, role: "alert", text });

    const head = (title, sub) => h("div", { class: "auth-head" },
      h("div", { class: "brand" }, brandMark(), h("span", { text: "Crypto Helper" })),
      h("h1", { id: "auth-title", text: title }),
      sub ? h("p", { text: sub }) : null);

    const fail = (form, err) => {
      form.querySelector(".notice")?.remove();
      form.prepend(notice(err instanceof ApiError ? err.message : String(err)));
      card.classList.remove("shake");
      void card.offsetWidth; // restart the animation
      card.classList.add("shake");
    };

    const busy = (form, on) => {
      for (const el of form.querySelectorAll("button, input")) el.disabled = on;
    };

    const finish = async () => {
      const me = await api("GET", "/api/auth/me", undefined, { retryAuth: false });
      overlay.remove();
      resolve(me);
    };

    // ---- first launch -------------------------------------------------------------------
    function setup() {
      const token = h("input", { class: "input", id: "setup-token", name: "token", required: true,
        autocomplete: "off", spellcheck: "false" });
      const pw = h("input", { class: "input", id: "setup-password", type: "password", required: true,
        minlength: "12", autocomplete: "new-password" });
      const pw2 = h("input", { class: "input", id: "setup-password2", type: "password", required: true,
        autocomplete: "new-password" });
      const form = h("form", {},
        head("Create the super account", "First launch. On the server, run: sudo crypto-helper setup token"),
        h("div", { class: "field" }, h("label", { for: "setup-token", text: "Setup token" }), token),
        h("div", { class: "field" }, h("label", { for: "setup-password", text: "Password (12+ characters)" }), pw),
        h("div", { class: "field" }, h("label", { for: "setup-password2", text: "Repeat password" }), pw2),
        h("button", { class: "btn btn-primary btn-block", type: "submit", text: "Create account" }));
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (pw.value !== pw2.value) return fail(form, "The passwords don't match.");
        busy(form, true);
        try {
          await api("POST", "/api/setup", { token: token.value.trim(), password: pw.value });
          login({ username: "super", message: "The super account exists. Sign in with it." });
        } catch (err) {
          busy(form, false);
          fail(form, err);
        }
      });
      fill(card, form);
      token.focus();
    }

    // ---- username and password ----------------------------------------------------------
    function login({ username: name = username, message = null } = {}) {
      const user = h("input", { class: "input", id: "login-username", name: "username", required: true,
        autocomplete: "username", autocapitalize: "none", spellcheck: "false", value: name });
      const pw = h("input", { class: "input", id: "login-password", name: "password", type: "password",
        required: true, autocomplete: "current-password" });
      const sub = reason === "expired"
        ? "Your session ended. Sign in to carry on where you left off."
        : "Sign in to your dashboard.";
      const form = h("form", {},
        head("Sign in", sub),
        message ? notice(message, "info") : null,
        h("div", { class: "field" }, h("label", { for: "login-username", text: "Username" }), user),
        h("div", { class: "field" }, h("label", { for: "login-password", text: "Password" }), pw),
        h("button", { class: "btn btn-primary btn-block", type: "submit", text: "Sign in" }));
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        busy(form, true);
        const creds = { username: user.value.trim(), password: pw.value };
        try {
          await api("POST", "/api/auth/login", creds, { retryAuth: false });
          await finish();
        } catch (err) {
          busy(form, false);
          if (err.status === 401 && err.data?.totp_required) return code(creds);
          pw.value = "";
          fail(form, err);
          pw.focus();
        }
      });
      fill(card, form);
      (name ? pw : user).focus();
    }

    // ---- second factor ------------------------------------------------------------------
    function code(creds, recovery = false) {
      const input = recovery
        ? h("input", { class: "input", id: "login-code", required: true, autocomplete: "off",
            placeholder: "xxxxx-xxxxx", spellcheck: "false" })
        : h("input", { class: "input code", id: "login-code", required: true, inputmode: "numeric",
            autocomplete: "one-time-code", maxlength: "6", pattern: "[0-9 ]{6,7}", placeholder: "000000" });
      const form = h("form", {},
        head("Two-factor code", recovery
          ? "Enter one of your recovery codes. Each works once."
          : "Enter the 6-digit code from your authenticator app."),
        h("div", { class: "field" },
          h("label", { for: "login-code", text: recovery ? "Recovery code" : "Code" }), input),
        h("button", { class: "btn btn-primary btn-block", type: "submit", text: "Verify" }),
        h("div", { class: "auth-foot" },
          h("button", { class: "linklike", type: "button", text: "Back",
            onclick: () => login({ username: creds.username }) }),
          h("button", { class: "linklike", type: "button",
            text: recovery ? "Use the app code instead" : "Use a recovery code",
            onclick: () => code(creds, !recovery) })));
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        busy(form, true);
        try {
          await api("POST", "/api/auth/login", { ...creds, totp: input.value.trim() }, { retryAuth: false });
          await finish();
        } catch (err) {
          busy(form, false);
          if (err.status === 401 && !err.data?.totp_required) {
            return login({ username: creds.username, message: null }); // locked or password changed
          }
          input.value = "";
          fail(form, err);
          input.focus();
        }
      });
      fill(card, form);
      input.focus();
    }

    if (mode === "setup") setup();
    else login();
  });
}
