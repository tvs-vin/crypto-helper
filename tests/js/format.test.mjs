// Money display: text only, never floating point.
import assert from "node:assert/strict";
import { test } from "node:test";

import { group, money } from "../../app/web/js/format.js";

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
