// Guided wallet setup: choose a kind of wallet, get it safely, look after the recovery phrase,
// test it, then add it here by its PUBLIC address. Crypto Helper never sees a key or a
// recovery phrase (the server refuses one if it's pasted anywhere), and can never move coins.

import { api } from "../api.js";
import { emit } from "../bus.js";
import { fill, h } from "../dom.js";
import { button, field, form, input, select, sheet } from "../ui.js";

// Examples, not endorsements: well-known options people commonly use. Check current reviews.
const KINDS = {
  hardware: {
    title: "Hardware wallet",
    pitch: "A small device that keeps your keys offline. The safest place for savings you won't touch often.",
    examples: "Ledger, Trezor, BitBox02; Coldcard (Bitcoin only)",
    walletKind: "onchain",
    get: [
      "Buy it from the maker's own website, never second-hand or from a marketplace seller.",
      "Check the packaging is sealed and untouched. If anything looks opened, don't use it.",
      "Set it up with the maker's official app, from their website.",
      "The device itself must show you a new recovery phrase. A phrase that came printed in the box is a scam: throw it away.",
    ],
    test: "Open the receive screen in the app, and check the address on the device's own screen matches.",
  },
  phone: {
    title: "Phone wallet app",
    pitch: "A self-custody app on your phone. Handy for smaller, everyday amounts.",
    examples: "BlueWallet (Bitcoin), MetaMask (Ethereum), Phantom (Solana); Trust Wallet, Exodus (many coins)",
    walletKind: "onchain",
    get: [
      "Install it only from the official app store, following the link on the project's own website.",
      "Check the publisher's name: fake look-alike wallet apps exist and steal coins.",
      "Set a strong phone lock and the app's own PIN or fingerprint lock.",
      "Let the app make a new wallet; it will show you a new recovery phrase.",
    ],
    test: "Open Receive in the app and copy the address from there (never retype it).",
  },
  desktop: {
    title: "Desktop wallet app",
    pitch: "Self-custody software on a computer. More control, and pairs well with a hardware wallet.",
    examples: "Sparrow, Electrum (Bitcoin); Exodus (many coins)",
    walletKind: "onchain",
    get: [
      "Download it only from the project's own website, and check the download if they show how.",
      "Keep the computer up to date, with nothing on it you don't trust.",
      "Let the app make a new wallet; it will show you a new recovery phrase.",
    ],
    test: "Open Receive in the app and copy the address from there (never retype it).",
  },
  exchange: {
    title: "Exchange account",
    pitch: "The exchange holds the coins for you. Easiest for buying and selling, but they're not in your own keys: if the exchange fails or freezes your account, you can't get at them.",
    examples: "Available in the US: Coinbase, Kraken, Gemini",
    walletKind: "exchange",
    get: [
      "Sign up on the exchange's real website: type the address yourself or use a bookmark, never a link from an email or ad.",
      "Turn on two-factor login with an authenticator app (not text messages).",
      "Turn on the withdrawal address allowlist (or similar) if the exchange has it.",
      "Never share a login code with anyone, including someone who says they're support.",
    ],
    test: "Withdrawals are where mistakes happen: send a small amount first, on the network the exchange shows.",
  },
};

const PHRASE = [
  "Write the words on paper (or stamp them in metal), in order, by hand.",
  "Never take a photo of it, and never type it into a computer, a phone, notes, email, cloud storage, or any website. That includes this one: Crypto Helper will never ask for it.",
  "Keep it somewhere safe and private. A second copy in another safe place protects against fire or loss.",
  "Anyone who sees it can take your coins. Nobody honest will ever ask for it: \"support\", \"airdrops\" and \"wallet check\" sites asking for it are scams.",
];

const TEST = [
  "Send a small amount first, and wait until it arrives. Only then send more.",
  "Each network has its own addresses: sending on the wrong network can lose the coins. Pick the same network on both sides.",
];

export function walletGuide(body, ctx) {
  sheet(body, "Set up a wallet", (close) => {
    const area = h("div", { class: "guide panel-stack" });
    let kindKey = null;
    const steps = ["kind", "get", "phrase", "test", "add"];
    const show = (step) => {
      const k = KINDS[kindKey];
      const nav = (back, next, nextLabel = "Next", ready = () => true) => h("div", { class: "actions" },
        back ? button("Back", { data: { action: "guide-back" }, onclick: () => show(back) }) : button("Cancel", { onclick: close }),
        next ? button(nextLabel, { kind: "btn-primary", data: { action: "guide-next" },
          onclick: (e) => { if (ready()) show(next); else e.currentTarget.closest(".guide").querySelector(".guide-warn")?.classList.remove("hidden"); } }) : null);
      const checklist = (items) => {
        const boxes = items.map((t) => h("input", { type: "checkbox" }));
        const list = h("div", { class: "guide-checks" }, items.map((t, i) => h("label", { class: "check" }, boxes[i], h("span", { text: t }))));
        return { list, done: () => boxes.every((b) => b.checked) };
      };
      const progress = h("ol", { class: "guide-steps", "aria-label": "Steps" },
        (kindKey === "exchange" ? steps.filter((s) => s !== "phrase") : steps).map((s) =>
          h("li", { class: s === step ? "current" : "", text: { kind: "Kind", get: "Get it", phrase: "Phrase", test: "Test", add: "Add" }[s] })));
      const warn = h("p", { class: "guide-warn warn-text small hidden", text: "Tick each one first: they're the things that keep your coins safe." });

      if (step === "kind") {
        fill(area, progress, h("p", { class: "muted", text: "Which kind of wallet are you setting up? (Not sure? You can practise first with a paper wallet: it uses made-up balances.)" }),
          h("div", { class: "guide-kinds" }, Object.entries(KINDS).map(([key, kk]) => h("button", {
            class: `guide-kind${key === kindKey ? " selected" : ""}`, type: "button", dataset: { kind: key },
            onclick: () => { kindKey = key; show("get"); } },
          h("strong", { text: kk.title }), h("span", { class: "small", text: kk.pitch }),
          h("span", { class: "muted small", text: `For example: ${kk.examples}` })))),
          nav(null, null));
      } else if (step === "get") {
        const c = checklist(k.get);
        fill(area, progress, h("h3", { text: `Get your ${k.title.toLowerCase()} safely` }), c.list, warn,
          nav("kind", kindKey === "exchange" ? "test" : "phrase", "Next", c.done));
      } else if (step === "phrase") {
        const c = checklist(PHRASE);
        fill(area, progress, h("h3", { text: "Look after your recovery phrase" }),
          h("p", { class: "muted", text: "The recovery phrase (12 or 24 words) is the wallet. If you lose it you lose the coins; if someone else sees it they can take them." }),
          c.list, warn, nav("get", "test", "Next", c.done));
      } else if (step === "test") {
        const c = checklist([k.test, ...TEST]);
        fill(area, progress, h("h3", { text: "Test it before you trust it" }), c.list, warn,
          nav(kindKey === "exchange" ? "get" : "phrase", "add", "Next", c.done));
      } else {
        fill(area, progress, addForm(k, ctx, close, () => show("test")));
      }
    };
    show("kind");
    return area;
  });
}

function addForm(k, ctx, close, back) {
  const exchange = k.walletKind === "exchange";
  const name = input({ name: "name", required: true, maxlength: "64", spellcheck: "false", placeholder: exchange ? "Coinbase" : "Ledger savings" });
  const nick = input({ name: "nickname", maxlength: "64", placeholder: "Shown as the big title (optional)" });
  const provider = input({ name: "provider", maxlength: "64", placeholder: exchange ? "Coinbase, Kraken, Gemini…" : "Ledger, MetaMask, Sparrow…" });
  const network = select([["", "Loading…"]], "", { name: "network" });
  const address = input({ name: "address", maxlength: "128", spellcheck: "false", autocomplete: "off",
    placeholder: "The wallet's receive address" });
  if (!exchange) {
    api("GET", "/api/meta/networks").then((m) => fill(network, ...[["", "Choose the network…"], ...Object.entries(m.networks)]
      .map(([v, t]) => h("option", { value: v, text: t }))));
  }
  return form([
    h("h3", { text: "Add it to Crypto Helper" }),
    h("p", { class: "muted", text: exchange
      ? "Crypto Helper keeps track of what the account holds (you set the balances). It never logs in to the exchange."
      : "Crypto Helper tracks it by its public address only. It can't move coins, and it must never see the recovery phrase." }),
    h("div", { class: "grid-2" }, field("Name", name, "Unique, e.g. the device or app"), field("Nickname", nick)),
    h("div", { class: "grid-2" }, field(exchange ? "Exchange" : "Wallet maker or app", provider),
      exchange ? null : field("Network", network, "The network this address is on.")),
    exchange ? null : field("Public address", address, "Copy it from Receive. Never a recovery phrase or private key."),
    h("div", { class: "actions" }, button("Back", { onclick: back }),
      button("Add wallet", { kind: "btn-primary", type: "submit", data: { action: "guide-add" } })),
  ], async () => {
    if (!exchange && address.value.trim() && !network.value) throw new Error("Choose the network the address is on.");
    const w = await api("POST", "/api/wallets", {
      name: name.value, nickname: nick.value || null, kind: k.walletKind, provider: provider.value || null,
      network: exchange ? null : network.value || null, address: exchange ? null : address.value.trim() || null,
      tags: ["guided"], notes: `Set up with the guide: ${k.title.toLowerCase()}.`,
    });
    close();
    ctx.toast("Wallet added", `${w.display_name || w.name}: set its balances with “Set balance”.`);
    emit("wallets-changed");
  });
}

