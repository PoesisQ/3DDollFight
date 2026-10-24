import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "../vendor/three.module.min.js";
import { createAvatar } from "../avatar.js";
import { limbGeometry, SelfLimbs, selfViewTransform } from "../self-limbs.js";

test("limb extraction excludes torso triangles and preserves normalized weights / material groups", () => {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute(
        "position",
        new THREE.Float32BufferAttribute(new Float32Array(18), 3),
    );
    geometry.setAttribute(
        "skinIndex",
        new THREE.Uint16BufferAttribute(
            [
                1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                0, 0, 0,
            ],
            4,
        ),
    );
    geometry.setAttribute(
        "skinWeight",
        new THREE.Uint8BufferAttribute(
            [
                255, 0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255, 0,
                0, 0, 255, 0, 0, 0,
            ],
            4,
            true,
        ),
    );
    geometry.setIndex([0, 1, 2, 3, 4, 5, 0, 1, 3]);
    geometry.addGroup(0, 3, 2);
    geometry.addGroup(3, 6, 0);
    const subset = limbGeometry(geometry, new Set([1]));
    assert.equal(subset.index.count, 3);
    assert.deepEqual(subset.groups, [{ start: 0, count: 3, materialIndex: 2 }]);
    assert.equal(subset.attributes.skinWeight.getX(0), 1);
    assert.notEqual(
        subset.attributes.position.array,
        geometry.attributes.position.array,
    );
    assert.equal(geometry.index.count, 9);
});

test("view pass shares animated skinning but leaves the global avatar and combat bones unchanged", () => {
    const parents = [
        -1, 0, 1, 2, 3, 2, 5, 6, 2, 8, 9, 0, 11, 12, 13, 0, 15, 16, 17,
    ];
    const rest = [
        [0, 0.95, 0],
        [0, 1.14, 0],
        [0, 1.38, 0],
        [0, 1.53, 0],
        [0, 1.65, 0],
        [0.22, 1.38, 0],
        [0.5, 1.38, 0],
        [0.78, 1.38, 0],
        [-0.22, 1.38, 0],
        [-0.5, 1.38, 0],
        [-0.78, 1.38, 0],
        [0.105, 0.95, 0],
        [0.105, 0.52, 0.015],
        [0.105, 0.09, 0],
        [0.105, 0.04, 0.17],
        [-0.105, 0.95, 0],
        [-0.105, 0.52, 0.015],
        [-0.105, 0.09, 0],
        [-0.105, 0.04, 0.17],
    ];
    const avatar = createAvatar(rest, parents);
    const view = new SelfLimbs(avatar);
    assert.equal(view.parts.length, 4);
    for (const { mesh, source: original } of view.parts) {
        const fade = mesh.geometry.attributes.selfLimbFade.array;
        assert.ok(fade.some((v) => v < 0.1) && fade.some((v) => v === 1));
        assert.ok(fade.every((v) => v >= 0 && v <= 1));
        assert.equal(original.geometry.attributes.selfLimbFade, undefined);
    }
    avatar.group.position.set(0.6, 0, -0.3);
    avatar.group.rotation.y = 0.7;
    avatar.bones[5].rotation.z = -1.2;
    avatar.bones[6].rotation.y = -0.4;
    avatar.group.updateMatrixWorld(true);
    const snapshot = avatar.bones.map((b) => b.matrixWorld.toArray());
    const source = view.parts[0].source;
    source.skeleton.update();
    const sourceMatrix = source.matrixWorld.toArray();
    const camera = new THREE.PerspectiveCamera(52, 1.5, 0.04, 40);
    camera.position.set(3, 1.1, 0);
    camera.lookAt(0, 1, 0);
    camera.updateMatrixWorld(true);
    const renderer = {
        autoClear: true,
        clearDepth() {},
        render(scene) {
            scene.updateMatrixWorld(true);
            for (const { mesh } of view.parts) mesh.onBeforeRender();
        },
    };
    view.draw(renderer, camera);
    assert.equal(renderer.autoClear, true);
    assert.deepEqual(
        avatar.bones.map((b) => b.matrixWorld.toArray()),
        snapshot,
    );
    assert.deepEqual(source.matrixWorld.toArray(), sourceMatrix);
    const mesh = view.parts[0].mesh;
    assert.equal(mesh.skeleton, source.skeleton);
    assert.notEqual(mesh.material, source.material);
    assert.equal(mesh.material.map, source.material.map);
    assert.deepEqual(
        mesh.material.color.toArray(),
        source.material.color.toArray(),
    );
    const head = avatar.bones[4].getWorldPosition(new THREE.Vector3());
    const expected = new THREE.Matrix4().multiplyMatrices(
        selfViewTransform(view.camera, head),
        source.matrixWorld,
    );
    assert.deepEqual(mesh.matrixWorld.toArray(), expected.toArray());
    assert.deepEqual(
        mesh.bindMatrixInverse.toArray(),
        source.bindMatrixInverse.toArray(),
    );
    assert.equal(avatar.group.visible, true);
    view.draw(renderer, camera, true);
    assert.deepEqual(mesh.matrixWorld.toArray(), source.matrixWorld.toArray());
    assert.deepEqual(
        view.camera.projectionMatrix.toArray(),
        camera.projectionMatrix.toArray(),
    );
    view.dispose();
    assert.equal(source.geometry.attributes.position.count > 0, true);
    avatar.dispose();
});
