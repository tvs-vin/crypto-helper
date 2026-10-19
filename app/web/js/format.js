// Display formatting. Money and amounts arrive from the server as exact decimal strings;
// they're only ever re-grouped as text here, never turned into floating-point numbers.

const FIAT_SYMBOL = { usd: "$", eur: "€", gbp: "£", jpy: "¥", cad: "CA$", aud: "A$" };

/** "1234567.891" -> "1,234,567.891" (text only; no rounding). */
export function group(decimal) {
  if (decimal === null || decimal === undefined || decimal === "") return "";
  const [sign, body] = decimal.startsWith("-") ? ["-", decimal.slice(1)] : ["", decimal];
  const [int, frac] = body.split(".");
  return sign + int.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (frac ? `.${frac}` : "");
}

export function money(value, fiat = "usd") {
  if (value === null || value === undefined) return "—";
  const sym = FIAT_SYMBOL[fiat] ?? "";
  // "369.9" -> "369.90": a one-digit fraction gets its cents (text only).
  const cents = /\.\d$/.test(value) ? `${value}0` : value;
  return cents.startsWith("-") ? `-${sym}${group(cents.slice(1))}` : `${sym}${group(cents)}`;
}

export const amount = (value) => (value === null || value === undefined ? "—" : group(value));

/** Percent change for display (not money, so a rounded number is fine here). */
export function percent(value) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}%`;
}

/** A change over time from the server ({amount, percent}): "+$12.50 (+3.10%)", and up/down. */
export function moneyChange(c, fiat) {
  const zero = /^-?0(\.0+)?$/.test(c.amount);
  const up = !c.amount.startsWith("-");
  return { cls: zero ? "" : up ? "up" : "down",
    text: `${up && !zero ? "+" : ""}${money(c.amount, fiat)}${c.percent === null ? "" : ` (${percent(c.percent)})`}` };
}

export const changeClass = (value) =>
  value === null || value === undefined ? "" : Number(value) > 0 ? "up" : Number(value) < 0 ? "down" : "";

/** Compare two decimal strings exactly (for sorting by value or amount). */
export function cmpDecimal(a, b) {
  if (a === b) return 0;
  if (a === null || a === undefined) return -1;
  if (b === null || b === undefined) return 1;
  const neg = (s) => s.startsWith("-");
  if (neg(a) !== neg(b)) return neg(a) ? -1 : 1;
  const flip = neg(a) ? -1 : 1;
  const [ai, af = ""] = a.replace("-", "").split(".");
  const [bi, bf = ""] = b.replace("-", "").split(".");
  const ia = ai.replace(/^0+(?=\d)/, "");
  const ib = bi.replace(/^0+(?=\d)/, "");
  if (ia.length !== ib.length) return (ia.length - ib.length > 0 ? 1 : -1) * flip;
  if (ia !== ib) return (ia > ib ? 1 : -1) * flip;
  const n = Math.max(af.length, bf.length);
  const fa = af.padEnd(n, "0");
  const fb = bf.padEnd(n, "0");
  return fa === fb ? 0 : (fa > fb ? 1 : -1) * flip;
}

/** The server sends naive UTC times ("2026-10-14T23:24:20"); read them as UTC. */
export function utc(s) {
  if (!s) return null;
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(s) ? s : `${s}Z`);
}

export function ago(s) {
  const d = utc(s);
  if (!d) return "";
  const sec = Math.round((Date.now() - d.getTime()) / 1000);
  if (sec < 45) return "just now";
  if (sec < 90) return "1 min ago";
  if (sec < 3600) return `${Math.round(sec / 60)} min ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)} h ago`;
  return d.toLocaleDateString();
}

export function when(s) {
  const d = utc(s);
  return d ? d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "";
}
