// Money display: text only, never floating point.
import assert from "node:assert/strict";
import { test } from "node:test";

import { group, money, moneyChange } from "../../app/web/js/format.js";

test("group adds thousands separators and keeps every digit", () => {
  assert.equal(group("1234567.891234567890123"), "1,234,567.891234567890123");
  assert.equal(group("-1000"), "-1,000");
  assert.equal(group("12"), "12");
});

test("money puts the sign first and gives a one-digit fraction its cents", () => {
  assert.equal(money("369.9"), "$369.90");
  assert.equal(money("-1234.5", "eur"), "-€1,234.50");
  assert.equal(money("0.000123"), "$0.000123");
  assert.equal(money("1500", "jpy"), "¥1,500");
  assert.equal(money(null), "—");
});

test("moneyChange: sign, colour and percent from the server's exact strings", () => {
  assert.deepEqual(moneyChange({ amount: "435.00", percent: "29.00" }, "usd"), { cls: "up", text: "+$435.00 (+29.00%)" });
  assert.deepEqual(moneyChange({ amount: "-1234.5", percent: "-3.10" }, "eur"), { cls: "down", text: "-€1,234.50 (-3.10%)" });
  assert.deepEqual(moneyChange({ amount: "0.00", percent: "0.00" }, "usd"), { cls: "", text: "$0.00 (0.00%)" });
  assert.deepEqual(moneyChange({ amount: "12", percent: null }, "jpy"), { cls: "up", text: "+¥12" }); // from zero: no percent
});
