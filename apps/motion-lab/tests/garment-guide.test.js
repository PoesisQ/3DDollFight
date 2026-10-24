import test from "node:test";
import assert from "node:assert/strict";
import { skirtGuide, projectGarmentPoint } from "../garment-guide.js";

const segments = 24,
    rows = 9,
    rest = [];
for (let r = 0; r < rows; r++)
    for (let c = 0; c < segments; c++) {
        const a = (c * 2 * Math.PI) / segments;
        rest.push(
            (0.13 + r * 0.013) * Math.sin(a),
            1 - r * 0.05,
            (0.1 + r * 0.012) * Math.cos(a),
        );
    }
const legs = [
    { a: [-0.075, 0.94, 0], b: [-0.075, 1.13, 0.38], radius: 0.08 },
    { a: [0.075, 0.94, 0], b: [0.075, 0.5, 0], radius: 0.08 },
];
test("high-kick corrective lifts the front hem, fixes the waist and keeps the back draped", () => {
    const guide = skirtGuide(rest, segments, rows, legs);
    assert.deepEqual(guide.slice(0, 72), Float64Array.from(rest.slice(0, 72)));
    const front = 8 * segments * 3,
        back = (8 * segments + 12) * 3;
    assert.ok(guide[front + 1] > rest[front + 1] + 0.25);
    assert.ok(Math.abs(guide[back + 1] - rest[back + 1]) < 0.02);
});
test("cloth guide commutes with an arena turn and translation", () => {
    const transform = (p) => [p[2] + 2, p[1], -p[0] - 1];
    const flat = [];
    for (let i = 0; i < rest.length; i += 3)
        flat.push(...transform(rest.slice(i, i + 3)));
    const changed = skirtGuide(
        flat,
        segments,
        rows,
        legs.map((c) => ({ ...c, a: transform(c.a), b: transform(c.b) })),
    );
    const original = skirtGuide(rest, segments, rows, legs);
    for (let i = 0; i < rest.length; i += 3) {
        const expected = transform(Array.from(original.slice(i, i + 3)));
        for (let k = 0; k < 3; k++)
            assert.ok(Math.abs(expected[k] - changed[i + k]) < 1e-10);
    }
});
test("dense correction is bounded and continuous through the capsule axis", () => {
    let previous = null;
    for (let x = -0.15; x <= 0.15; x += 0.0005) {
        const point = [x, 0.7, 0.001];
        const p = projectGarmentPoint(point, legs);
        assert.ok(p.every(Number.isFinite));
        assert.ok(Math.hypot(...p.map((v, k) => v - point[k])) <= 0.02500001);
        if (previous)
            assert.ok(Math.hypot(...p.map((v, k) => v - previous[k])) < 0.002);
        previous = p;
    }
    const point = [0.08, 0.7, 0.078];
    const p = projectGarmentPoint(point, legs);
    assert.ok(p[2] > point[2], "shallow contact moves away from the leg");
});
