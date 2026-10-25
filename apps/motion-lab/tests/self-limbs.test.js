import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "../vendor/three.module.min.js";
import { createAvatar } from "../avatar.js";
import {
    bodyGeometry,
    SelfLimbs,
    configureBodyCamera,
    updateBodyBounds,
    garmentBatches,
    skinBounds,
} from "../self-limbs.js";

test("body proxy omits head triangles but retains mixed shoulder/torso triangles and shared buffers", () => {
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
    geometry.attributes.skinIndex.setX(4, 2); // shoulder
    geometry.attributes.skinIndex.setX(5, 3); // arm: mixed torso triangle must stay
    geometry.addGroup(0, 3, 2);
    geometry.addGroup(3, 6, 0);
    const subset = bodyGeometry(geometry, new Set([1]));
    assert.equal(subset.index.count, 3);
    assert.deepEqual(subset.groups, [{ start: 0, count: 3, materialIndex: 0 }]);
    assert.equal(subset.attributes.skinWeight.getX(0), 1);
    assert.equal(
        subset.attributes.position.array,
        geometry.attributes.position.array,
    );
    assert.equal(geometry.index.count, 9);
    // With no head influence, torso/shoulder/arm boundaries stay intact.
    assert.equal(bodyGeometry(geometry, new Set([9])), geometry);
    assert.equal(bodyGeometry(geometry, new Set([0, 1, 2, 3])), null);
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
    assert.equal(view.parts.length, 1);
    assert.equal(
        view.parts[0].mesh.geometry.attributes.position,
        view.parts[0].source.geometry.attributes.position,
    );
    assert.equal(
        view.parts[0].mesh.geometry.attributes.selfLimbFade,
        undefined,
    );
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
    assert.deepEqual(mesh.matrixWorld.toArray(), source.matrixWorld.toArray());
    assert.ok(
        view.camera.position.y >
            avatar.bones[4].getWorldPosition(new THREE.Vector3()).y + 0.1,
    );
    const wrist = avatar.bones[7]
        .getWorldPosition(new THREE.Vector3())
        .project(view.camera);
    for (const yaw of [0, Math.PI / 2, Math.PI, Math.PI * 1.9]) {
        avatar.group.rotation.y = yaw;
        avatar.group.updateMatrixWorld(true);
        configureBodyCamera(
            view.camera,
            avatar,
            view.bindHeadInverse,
            camera.aspect,
        );
        const projected = avatar.bones[7]
            .getWorldPosition(new THREE.Vector3())
            .project(view.camera);
        assert.ok(
            projected.distanceTo(wrist) < 1e-10,
            "head-attached body stays connected through global turns",
        );
        const box = updateBodyBounds(
            source,
            view.parts[0].bounds,
            new THREE.Box3(),
        );
        for (const i of new Set(mesh.geometry.index.array)) {
            const p = source
                .getVertexPosition(i, new THREE.Vector3())
                .applyMatrix4(source.matrixWorld);
            assert.ok(
                box.containsPoint(p),
                "culling bound must enclose every skinned vertex, including mixed weights",
            );
        }
    }
    view.draw(renderer, camera);
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

test("garment batches retain every triangle and conservatively bound animated shared vertices", () => {
    const geometry = new THREE.CylinderGeometry(0.2, 0.4, 0.6, 32, 8, true);
    const count = geometry.attributes.position.count;
    const indices = new Uint16Array(count * 4),
        weights = new Float32Array(count * 4);
    for (let i = 0; i < count; i++) {
        indices[i * 4 + 1] = 1;
        weights[i * 4] = 0.4;
        weights[i * 4 + 1] = 0.6;
    }
    geometry.setAttribute(
        "skinIndex",
        new THREE.Uint16BufferAttribute(indices, 4),
    );
    geometry.setAttribute(
        "skinWeight",
        new THREE.Float32BufferAttribute(weights, 4),
    );
    const source = new THREE.SkinnedMesh(
        geometry,
        new THREE.MeshBasicMaterial(),
    );
    const bones = [new THREE.Bone(), new THREE.Bone()];
    source.add(...bones);
    source.bind(new THREE.Skeleton(bones));
    const batches = garmentBatches(geometry);
    assert.equal(batches.length, 16);
    const triangles = (g) => {
        const result = [];
        for (let i = 0; i < g.index.count; i += 3)
            result.push(
                [
                    g.index.getX(i),
                    g.index.getX(i + 1),
                    g.index.getX(i + 2),
                ].join(","),
            );
        return result;
    };
    assert.deepEqual(
        batches.flatMap(triangles).sort(),
        triangles(geometry).sort(),
    );
    const bounds = batches.map((g) => skinBounds(source, g));
    bones[0].rotation.z = 0.8;
    bones[1].rotation.x = -0.5;
    bones[1].position.y = 0.4;
    source.position.set(-3, 1, 2);
    source.updateMatrixWorld(true);
    for (let n = 0; n < batches.length; n++) {
        const batch = batches[n];
        assert.equal(batch.attributes.position, geometry.attributes.position);
        const box = updateBodyBounds(source, bounds[n], new THREE.Box3());
        for (const i of new Set(batch.index.array)) {
            const p = source
                .getVertexPosition(i, new THREE.Vector3())
                .applyMatrix4(source.matrixWorld);
            assert.ok(box.containsPoint(p));
        }
    }
});
