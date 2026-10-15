// node --test tests/js/
import assert from "node:assert/strict";
import test from "node:test";
import { cascade, clampRect, gridLayout, masterLayout, snapZone, zoneRect } from "../../app/web/js/tiling.js";

const AREA = { x: 0, y: 0, w: 1200, h: 800 };

test("snap zones: edges, corners, top", () => {
  assert.equal(snapZone(5, 400, AREA), "left");
  assert.equal(snapZone(1195, 400, AREA), "right");
  assert.equal(snapZone(600, 5, AREA), "max");
  assert.equal(snapZone(5, 10, AREA), "tl");
  assert.equal(snapZone(1195, 790, AREA), "br");
  assert.equal(snapZone(600, 400, AREA), null);
});

test("zone rects split the area with gaps and never overlap", () => {
  const l = zoneRect("left", AREA, 8);
  const r = zoneRect("right", AREA, 8);
  assert.deepEqual(l, { x: 8, y: 8, w: 588, h: 784 });
  assert.ok(l.x + l.w < r.x);
  const tl = zoneRect("tl", AREA, 8);
  const bl = zoneRect("bl", AREA, 8);
  assert.ok(tl.y + tl.h < bl.y);
  assert.deepEqual(zoneRect("max", AREA, 8), { x: 8, y: 8, w: 1184, h: 784 });
});

function overlaps(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

for (const [name, fn] of [["grid", gridLayout], ["master", masterLayout]]) {
  test(`${name} layout: n windows, inside the area, no overlaps`, () => {
    for (let n = 1; n <= 9; n++) {
      const rects = fn(n, AREA, 8);
      assert.equal(rects.length, n);
      for (const r of rects) {
        assert.ok(r.x >= 0 && r.y >= 0 && r.x + r.w <= AREA.w && r.y + r.h <= AREA.h, JSON.stringify(r));
      }
      for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
        assert.ok(!overlaps(rects[i], rects[j]), `${name} n=${n}: ${i} overlaps ${j}`);
      }
    }
  });
}

test("master layout gives the first window the big left side", () => {
  const [main, ...stack] = masterLayout(3, AREA, 8);
  assert.ok(main.w > stack[0].w && main.h === 784);
});

test("clamp keeps windows inside and at least the minimum size", () => {
  assert.deepEqual(clampRect({ x: -50, y: 900, w: 100, h: 50 }, AREA), { x: 0, y: 640, w: 260, h: 160 });
  assert.deepEqual(clampRect({ x: 10, y: 10, w: 5000, h: 5000 }, AREA), { x: 0, y: 0, w: 1200, h: 800 });
});

test("cascade wraps instead of walking off screen", () => {
  const spots = Array.from({ length: 40 }, (_, i) => cascade(i, { w: 600, h: 400 }, AREA));
  for (const r of spots) assert.ok(r.x + r.w <= AREA.w && r.y + r.h <= AREA.h);
});
