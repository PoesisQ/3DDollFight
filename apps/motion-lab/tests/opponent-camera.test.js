import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "../vendor/three.module.min.js";
import { configureOpponentCamera } from "../projection.js";

test("both players see the opponent's entire pose at close range and narrow aspect", () => {
    for (const side of [-1, 1])
        for (const aspect of [0.65, 1, 1.8, 2.4])
            for (const gap of [0.55, 1.2, 3.5]) {
                const poses = [
                    [
                        [side * gap, 0.05, -0.2],
                        [side * gap, 1.75, 0],
                        [side * gap + 0.1, 1.3, 0.8],
                    ],
                    [
                        [side * gap, 0.04, 0],
                        [side * gap - 0.15, 1.5, -0.3],
                        [side * gap - 0.85, 1.65, 0.7],
                    ],
                    [
                        [side * gap, 0.05, -0.4],
                        [side * gap, 1.1, 0.3],
                    ],
                ];
                for (const pose of poses) {
                    const camera = new THREE.PerspectiveCamera();
                    configureOpponentCamera(
                        camera,
                        new THREE.Vector3(0, 1.65, 0.1),
                        pose,
                        aspect,
                    );
                    for (const p of pose) {
                        const screen = new THREE.Vector3(...p).project(camera);
                        assert.ok(
                            Math.abs(screen.x) < 0.9 &&
                                Math.abs(screen.y) < 0.9,
                        );
                        assert.ok(screen.z > -1 && screen.z < 1);
                    }
                }
            }
});
