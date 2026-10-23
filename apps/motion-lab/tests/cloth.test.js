import assert from "node:assert/strict";
import test from "node:test";
import { ClothSolver } from "../cloth.js";

function skirt() {
    const points = [],
        segments = 16,
        rows = 6;
    for (let r = 0; r < rows; r++)
        for (let c = 0; c < segments; c++) {
            const angle = (c / segments) * 2 * Math.PI;
            points.push(
                (0.14 + r * 0.02) * Math.sin(angle),
                1 - r * 0.08,
                (0.11 + r * 0.015) * Math.cos(angle),
            );
        }
    return new ClothSolver(points, segments, rows);
}
test("garment pins remain fixed and gravity relaxation stays finite", () => {
    const s = skirt();
    for (let k = 0; k < 120; k++) s.step(1 / 60, s.rest, []);
    assert.deepEqual(s.position.slice(0, 48), s.rest.slice(0, 48));
    assert.ok([...s.position].every(Number.isFinite));
    assert.ok(s.stretch().max < 1.25, `stretch ${s.stretch().max}`);
    assert.throws(() => s.step(0.5, s.rest, []), /substeps/);
});
test("feasible body contact stays within 5 mm while limiting garment stretch", () => {
    const s = skirt();
    const capsule = { a: [0.1, 0.82, 0], b: [0.1, 0.5, 0], radius: 0.13 };
    for (let k = 0; k < 60; k++) s.step(1 / 60, s.rest, [capsule]);
    for (let i = 48; i < s.position.length; i += 3) {
        const x = s.position[i],
            y = s.position[i + 1],
            z = s.position[i + 2];
        const cy = Math.max(0.5, Math.min(0.82, y));
        assert.ok(Math.hypot(x - 0.1, y - cy, z) >= 0.13 - 0.005);
    }
    assert.ok(s.stretch().max < 1.16);
    assert.equal(s.collisionReport([capsule]).fractionOver5mm, 0);
});

test("a fast thigh conflicting with pinned waist cannot tear cloth and reports residual contact", () => {
    const s = skirt();
    let capsules;
    for (let k = 0; k < 90; k++) {
        const angle = Math.min(Math.PI * 0.82, Math.max(0, (k - 10) * 0.08));
        capsules = [
            {
                a: [-0.075, 0.86, 0],
                b: [
                    -0.075,
                    0.86 - 0.35 * Math.cos(angle),
                    0.35 * Math.sin(angle),
                ],
                radius: 0.11,
            },
        ];
        s.step(1 / 60, s.rest, capsules);
        assert.ok(s.stretch().max < 1.2, `step ${k}: ${s.stretch().max}`);
    }
    assert.deepEqual(s.position.slice(0, 48), s.rest.slice(0, 48));
    assert.ok([...s.position].every(Number.isFinite));
    assert.ok(s.collisionReport(capsules).maxPenetration > 0.005);
    assert.throws(() => new ClothSolver([0, 0, NaN], 1, 1), /topology/);
});
test("fixed-step garment bake repeats bit-for-bit for moving anchors and colliders", () => {
    const a = skirt(),
        b = skirt();
    for (let k = 0; k < 90; k++) {
        const anchors = Float64Array.from(a.rest);
        for (let i = 0; i < anchors.length; i += 3)
            anchors[i] += 0.04 * Math.sin(k / 30);
        const capsules = [
            {
                a: [0.08, 0.9, 0],
                b: [0.08, 0.57, 0.15 * Math.sin(k / 50)],
                radius: 0.08,
            },
        ];
        a.step(1 / 60, anchors, capsules);
        b.step(1 / 60, anchors, capsules);
    }
    assert.deepEqual(a.position, b.position);
});
