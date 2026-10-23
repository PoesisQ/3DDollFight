import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "../vendor/three.module.min.js";
import { configureOffAxis } from "../projection.js";

for (const side of [-1, 1]) {
    test(`screen corners stay fixed for moving eye, player side ${side}`, () => {
        const center = new THREE.Vector3(-side * 0.55, 1.65, 0);
        const right = new THREE.Vector3(0, 0, side),
            up = new THREE.Vector3(0, 1, 0);
        const a = center
            .clone()
            .addScaledVector(right, -0.39)
            .addScaledVector(up, -0.19);
        const b = a.clone().addScaledVector(right, 0.78),
            c = a.clone().addScaledVector(up, 0.38);
        const camera = new THREE.PerspectiveCamera();
        for (const offset of [-0.3, 0, 0.3]) {
            const eye = new THREE.Vector3(-side, 1.5 + offset, offset);
            configureOffAxis(camera, eye, a, b, c);
            for (const [corner, x, y] of [
                [a, -1, -1],
                [b, 1, -1],
                [c, -1, 1],
            ]) {
                const projected = corner.clone().project(camera);
                assert.ok(Math.abs(projected.x - x) < 1e-9);
                assert.ok(Math.abs(projected.y - y) < 1e-9);
            }
        }
    });
}
test("eye behind screen cannot create a reversed frustum", () => {
    assert.throws(() =>
        configureOffAxis(
            new THREE.PerspectiveCamera(),
            new THREE.Vector3(0, 0, -1),
            new THREE.Vector3(-1, -1, 0),
            new THREE.Vector3(1, -1, 0),
            new THREE.Vector3(-1, 1, 0),
        ),
    );
});
