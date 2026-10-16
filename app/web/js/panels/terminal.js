// Terminal (terminal.use): the VM's own login prompt. First confirm it's you (password and
// a code from your authenticator app), then sign in to the VM with a Linux account. What's
// typed goes straight to the VM over a WebSocket and is never logged.

import { api } from "../api.js";
import { fill, h } from "../dom.js";
import { button, field, form, input } from "../ui.js";

const VENDOR = "/static/vendor/xterm";
let loading = null;

/** xterm.js is only fetched when a Terminal window first opens (it's ~380 KB). */
function loadXterm() {
  const script = (src) => new Promise((resolve, reject) => {
    const el = h("script", { src });
    el.addEventListener("load", resolve);
    el.addEventListener("error", () => reject(new Error(`Couldn't load ${src}`)));
    document.head.append(el);
  });
  loading ??= (async () => {
    document.head.append(h("link", { rel: "stylesheet", href: `${VENDOR}/xterm.css` }));
    await script(`${VENDOR}/xterm.js`);
    await Promise.all([script(`${VENDOR}/addon-canvas.js`), script(`${VENDOR}/addon-fit.js`)]);
  })();
  return loading;
}

function themeColors() {
  const css = getComputedStyle(document.documentElement);
  const v = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
  return {
    background: v("--c-desktop", "#0c0c13"), foreground: v("--c-text", "#e6e6f0"),
    cursor: v("--c-accent", "#7c5cff"),
    // A see-through accent for selections (only when the theme's accent is plain #rrggbb).
    selectionBackground: /^#[0-9a-f]{6}$/i.test(v("--c-accent", "")) ? `${v("--c-accent", "")}55` : undefined,
  };
}

export function renderTerminal(body, ctx) {
  const area = h("div", { class: "terminal-area" });
  body.append(area);
  body.classList.add("terminal-body");
  let session = null;
  ctx.signal.addEventListener("abort", () => session?.end());
  confirmForm();

  function confirmForm(message = null) {
    session?.end();
    session = null;
    const password = input({ type: "password", name: "password", autocomplete: "current-password", required: true });
    const code = input({ name: "code", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "8",
      required: true, class: "input code", placeholder: "123456" });
    fill(area, h("div", { class: "terminal-confirm panel-stack" },
      message ? h("div", { class: "notice" }, message) : null,
      h("h3", { text: "Confirm it's you" }),
      h("p", { class: "muted small", text: "A terminal is full access to the VM, so it asks again each time. Next you'll sign in to the VM itself with a Linux account (for example vin)." }),
      form([
        field("Your Crypto Helper password", password),
        field("Code from your authenticator app", code),
        h("div", { class: "actions" }, button("Open terminal", { kind: "btn-primary", type: "submit", data: { action: "open-terminal" } })),
      ], async () => {
        await loadXterm();
        const { ticket } = await api("POST", "/api/terminal/open", { password: password.value, code: code.value, cols: 100, rows: 30 });
        start(ticket);
      })));
  }

  function start(ticket) {
    const box = h("div", { class: "terminal-screen" });
    fill(area, box);
    const term = new window.Terminal({ fontFamily: '"JetBrains Mono", ui-monospace, monospace', fontSize: 13,
      cursorBlink: true, theme: themeColors(), allowProposedApi: false });
    // The canvas renderer goes in before open(): xterm then never adds <style> elements,
    // which the Content-Security-Policy would block.
    term.loadAddon(new window.CanvasAddon.CanvasAddon());
    const fit = new window.FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(box);
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/terminal/ws?ticket=${encodeURIComponent(ticket)}`);
    ws.binaryType = "arraybuffer";
    const enc = new TextEncoder();
    const sendSize = () => { if (ws.readyState === 1) ws.send(JSON.stringify({ resize: [term.cols, term.rows] })); };
    ws.addEventListener("open", () => { fit.fit(); sendSize(); term.focus(); });
    ws.addEventListener("message", (e) => term.write(new Uint8Array(e.data)));
    let ended = false;
    ws.addEventListener("close", () => {
      if (ended) return;
      ended = true;
      term.write("\r\n\x1b[2m[session ended]\x1b[0m\r\n");
      area.append(h("div", { class: "terminal-ended row" },
        h("span", { class: "muted small", text: "The session ended." }),
        button("New session", { kind: "btn-sm", data: { action: "new-session" }, onclick: () => confirmForm() })));
    });
    term.onData((d) => { if (ws.readyState === 1) ws.send(enc.encode(d)); });
    term.onResize(sendSize);
    const ro = new ResizeObserver(() => { try { fit.fit(); } catch { /* hidden */ } });
    ro.observe(box);
    session = {
      end() {
        ended = true;
        ro.disconnect();
        if (ws.readyState <= 1) ws.close();
        term.dispose();
      },
    };
  }
}
