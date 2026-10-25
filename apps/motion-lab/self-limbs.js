import * as THREE from "./vendor/three.module.min.js";

// Keep the connected body. Only omit head/hair triangles which would surround
// a camera inside the face. Positions, UVs, weights and morph buffers are shared;
// a mixed head/body mesh needs only a new index buffer, never a cut at the arms.
export function bodyGeometry(source, excludedBones) {
    const skin = source.getAttribute("skinIndex");
    const weights = source.getAttribute("skinWeight");
    if (!skin || !weights) return source;
    const excluded = new Uint8Array(skin.count);
    for (let i = 0; i < skin.count; i++) {
        let influence = 0;
        for (let k = 0; k < 4; k++)
            if (excludedBones.has(skin.getComponent(i, k)))
                influence += weights.getComponent(i, k);
        excluded[i] = influence > 0.5;
    }
    const count = source.index?.count ?? skin.count;
    const at = (i) => (source.index ? source.index.getX(i) : i);
    const groups = source.groups.length
        ? source.groups
        : [{ start: 0, count, materialIndex: 0 }];
    const indices = [],
        keptGroups = [];
    for (const group of groups) {
        const start = indices.length;
        for (
            let i = group.start;
            i < Math.min(count, group.start + group.count);
            i += 3
        ) {
            const triangle = [at(i), at(i + 1), at(i + 2)];
            if (triangle.some((v) => excluded[v])) continue;
            indices.push(...triangle);
        }
        if (indices.length > start)
            keptGroups.push({
                start,
                count: indices.length - start,
                materialIndex: group.materialIndex,
            });
    }
    if (!indices.length) return null;
    if (indices.length === count) return source;
    const geometry = new THREE.BufferGeometry();
    for (const [name, attribute] of Object.entries(source.attributes))
        geometry.setAttribute(name, attribute);
    geometry.morphAttributes = source.morphAttributes;
    geometry.morphTargetsRelative = source.morphTargetsRelative;
    geometry.setIndex(indices);
    geometry.groups = keptGroups;
    return geometry;
}

// Spatial draw batches, not decimation: every original garment triangle is
// present exactly once, with the same shared vertex attributes and material.
// This allows a mostly off-screen 100k-triangle skirt to submit only the visible
// sectors. Adjacent batches still meet at the identical skinned vertices.
export function garmentBatches(source) {
    const position = source.attributes.position;
    const box = new THREE.Box3().setFromBufferAttribute(position);
    const center = box.getCenter(new THREE.Vector3());
    const count = source.index?.count ?? position.count;
    const at = (i) => (source.index ? source.index.getX(i) : i);
    const groups = source.groups.length
        ? source.groups
        : [{ start: 0, count, materialIndex: 0 }];
    const packets = new Map();
    const p = new THREE.Vector3(),
        centroid = new THREE.Vector3();
    for (const group of groups)
        for (
            let i = group.start;
            i < Math.min(count, group.start + group.count);
            i += 3
        ) {
            const triangle = [at(i), at(i + 1), at(i + 2)];
            centroid.set(0, 0, 0);
            for (const v of triangle)
                centroid.add(p.fromBufferAttribute(position, v));
            centroid.multiplyScalar(1 / 3).sub(center);
            const sector = Math.min(
                7,
                Math.floor(
                    ((Math.atan2(centroid.z, centroid.x) + Math.PI) * 4) /
                        Math.PI,
                ),
            );
            const key = sector + (centroid.y > 0 ? 8 : 0);
            if (!packets.has(key)) packets.set(key, new Map());
            const materials = packets.get(key);
            if (!materials.has(group.materialIndex))
                materials.set(group.materialIndex, []);
            materials.get(group.materialIndex).push(...triangle);
        }
    return [...packets.values()].map((materials) => {
        const geometry = new THREE.BufferGeometry(),
            indices = [];
        for (const [name, attribute] of Object.entries(source.attributes))
            geometry.setAttribute(name, attribute);
        geometry.morphAttributes = source.morphAttributes;
        geometry.morphTargetsRelative = source.morphTargetsRelative;
        for (const [material, triangles] of materials) {
            geometry.addGroup(indices.length, triangles.length, material);
            for (const v of triangles) indices.push(v);
        }
        geometry.setIndex(indices);
        return geometry;
    });
}

// A weighted vertex lies inside the convex hull of its transformed influences.
// Per-bone bounds therefore conservatively enclose linear skinning, without
// skinning every vertex on the CPU. This often rejects the entire skirt/torso
// below the eye; unlike dropping legs by ankle height it cannot cut an arm.
export function skinBounds(mesh, geometry = mesh.geometry) {
    if (!mesh.isSkinnedMesh || geometry.morphAttributes.position?.length)
        return null;
    const position = geometry.attributes.position;
    const skin = geometry.attributes.skinIndex;
    const weight = geometry.attributes.skinWeight;
    const boxes = mesh.skeleton.bones.map(() => new THREE.Box3());
    const transforms = mesh.skeleton.boneInverses.map((inverse) =>
        new THREE.Matrix4().multiplyMatrices(inverse, mesh.bindMatrix),
    );
    const p = new THREE.Vector3();
    const vertices = geometry.index
        ? new Set(geometry.index.array)
        : Array.from({ length: position.count }, (_, i) => i);
    for (const i of vertices)
        for (let k = 0; k < 4; k++) {
            if (weight.getComponent(i, k) <= 0) continue;
            const bone = skin.getComponent(i, k);
            p.fromBufferAttribute(position, i).applyMatrix4(transforms[bone]);
            boxes[bone].expandByPoint(p);
        }
    return boxes.flatMap((box, i) =>
        box.isEmpty()
            ? []
            : [
                  {
                      bone: mesh.skeleton.bones[i],
                      sphere: box.getBoundingSphere(new THREE.Sphere()),
                  },
              ],
    );
}

export function updateBodyBounds(source, bounds, box) {
    box.makeEmpty();
    const prefix = new THREE.Matrix4().multiplyMatrices(
        source.matrixWorld,
        source.bindMatrixInverse,
    );
    const matrix = new THREE.Matrix4(),
        sphere = new THREE.Sphere(),
        corner = new THREE.Vector3();
    for (const entry of bounds) {
        matrix.multiplyMatrices(prefix, entry.bone.matrixWorld);
        sphere.copy(entry.sphere).applyMatrix4(matrix);
        box.expandByPoint(corner.copy(sphere.center).addScalar(sphere.radius));
        box.expandByPoint(corner.copy(sphere.center).addScalar(-sphere.radius));
    }
    // Existing garment shader permits at most 25 mm of surface correction.
    return box.expandByScalar(0.03);
}

// An eye fixed to the presentation double, instead of moving severed limbs in
// front of a distant opponent camera. It follows the head frame, so shoulders
// remain attached below/behind the eye even during an arena spin. The arena
// camera stays horizon-stable and frames the opponent for screen-based play.
export function configureBodyCamera(camera, avatar, bindHeadInverse, aspect) {
    const head = avatar.bones[4];
    const orientation = head
        .getWorldQuaternion(new THREE.Quaternion())
        .multiply(bindHeadInverse);
    const forward = new THREE.Vector3(0, 0, 1).applyQuaternion(orientation);
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(orientation);
    const height = avatar.rest[4][1] - avatar.rest[13][1];
    const scale = height / 1.56;
    camera.position
        .copy(head.getWorldPosition(new THREE.Vector3()))
        .addScaledVector(forward, -0.14 * scale)
        .addScaledVector(up, 0.14 * scale);
    camera.up.copy(up);
    camera.lookAt(
        camera.position.clone().add(forward).addScaledVector(up, -0.14),
    );
    camera.fov = 78;
    camera.aspect = aspect;
    camera.near = 0.012;
    camera.far = 8;
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld(true);
}

export class SelfLimbs {
    constructor(avatar) {
        this.avatar = avatar;
        this.scene = new THREE.Scene();
        // Neutral soft lighting avoids the previous grey/green hand colouring.
        this.scene.add(new THREE.HemisphereLight("#ffffff", "#d9c6b8", 1.2));
        this.key = new THREE.DirectionalLight("#fff5ec", 1.1);
        this.scene.add(this.key, this.key.target);
        this.camera = new THREE.PerspectiveCamera(78, 1, 0.012, 8);
        this.bindHeadInverse = avatar.bones[4]
            .getWorldQuaternion(new THREE.Quaternion())
            .invert();
        this.parts = [];
        this.frustum = new THREE.Frustum();
        this.projectionView = new THREE.Matrix4();
        this.bounds = new THREE.Box3();
        this.stats = { submittedTriangles: 0, culledMeshes: 0 };
        this.materials = new Map();
        const hiddenNodes = new Set();
        const head = avatar.vrm
            ? avatar.vrm.humanoid.getRawBoneNode("head")
            : avatar.bones[4];
        head.traverse((node) => {
            if (node.isBone) hiddenNodes.add(node);
        });
        const viewMaterial = (source) => {
            if (!this.materials.has(source)) {
                const copy = source.isMeshBasicMaterial
                    ? new THREE.MeshLambertMaterial({
                          color: source.color,
                          map: source.map,
                          alphaMap: source.alphaMap,
                          alphaTest: source.alphaTest,
                          transparent: source.transparent,
                          opacity: source.opacity,
                          side: source.side,
                          vertexColors: source.vertexColors,
                      })
                    : source.clone();
                // Original material alpha and opaque depth testing are retained.
                // No shoulder fades, artificial arm extensions or shader cutouts.
                copy.forceSinglePass = true;
                copy.onBeforeCompile = source.onBeforeCompile.bind(source);
                copy.customProgramCacheKey =
                    source.customProgramCacheKey.bind(source);
                this.materials.set(source, copy);
            }
            return this.materials.get(source);
        };
        avatar.group.traverse((source) => {
            if (!source.isMesh) return;
            for (
                let ancestor = source.parent;
                ancestor;
                ancestor = ancestor.parent
            )
                if (hiddenNodes.has(ancestor)) return;
            const excluded = new Set(
                source.skeleton?.bones.flatMap((bone, i) =>
                    hiddenNodes.has(bone) ? [i] : [],
                ) || [],
            );
            const geometry = bodyGeometry(source.geometry, excluded);
            if (!geometry) return;
            const material = Array.isArray(source.material)
                ? source.material.map(viewMaterial)
                : viewMaterial(source.material);
            const batches = source.userData.dollfightCage
                ? garmentBatches(geometry)
                : [geometry];
            for (const batch of batches) {
                const mesh = source.isSkinnedMesh
                    ? new THREE.SkinnedMesh(batch, material)
                    : new THREE.Mesh(batch, material);
                if (source.isSkinnedMesh) {
                    mesh.bind(source.skeleton, source.bindMatrix);
                    mesh.bindMode = "detached";
                    mesh.onBeforeRender = () =>
                        mesh.bindMatrixInverse.copy(source.bindMatrixInverse);
                }
                mesh.matrixAutoUpdate = false;
                mesh.frustumCulled = false;
                mesh.castShadow = false;
                mesh.receiveShadow = false;
                mesh.morphTargetInfluences = source.morphTargetInfluences;
                this.scene.add(mesh);
                this.parts.push({
                    mesh,
                    source,
                    bounds: skinBounds(source, batch),
                    ownsGeometry: batch !== source.geometry,
                });
            }
            if (source.userData.dollfightCage && geometry !== source.geometry)
                geometry.dispose();
        });
    }
    draw(renderer, viewCamera, physicalEye = false) {
        if (!this.parts.length) return;
        const camera = this.camera;
        if (physicalEye) {
            camera.copy(viewCamera);
            camera.updateMatrixWorld(true);
        } else {
            configureBodyCamera(
                camera,
                this.avatar,
                this.bindHeadInverse,
                viewCamera.aspect,
            );
        }
        this.key.position
            .copy(camera.position)
            .add(
                new THREE.Vector3(-0.4, 0.8, -0.5).applyQuaternion(
                    camera.quaternion,
                ),
            );
        this.key.target.position.copy(camera.position);
        this.frustum.setFromProjectionMatrix(
            this.projectionView.multiplyMatrices(
                camera.projectionMatrix,
                camera.matrixWorldInverse,
            ),
        );
        this.stats.submittedTriangles = 0;
        this.stats.culledMeshes = 0;
        for (const { mesh, source, bounds } of this.parts) {
            mesh.visible =
                source.visible &&
                (!bounds ||
                    this.frustum.intersectsBox(
                        updateBodyBounds(source, bounds, this.bounds),
                    ));
            if (mesh.visible)
                this.stats.submittedTriangles +=
                    (mesh.geometry.index?.count ??
                        mesh.geometry.attributes.position.count) / 3;
            else if (source.visible) this.stats.culledMeshes++;
            mesh.matrix.copy(source.matrixWorld);
            if (mesh.isSkinnedMesh) mesh.bindMatrix.copy(source.bindMatrix);
        }
        const clear = renderer.autoClear;
        renderer.autoClear = false;
        renderer.clearDepth();
        try {
            renderer.render(this.scene, camera);
        } finally {
            renderer.autoClear = clear;
        }
    }
    dispose() {
        for (const { mesh, ownsGeometry } of this.parts)
            if (ownsGeometry) mesh.geometry.dispose();
        for (const material of this.materials.values()) material.dispose();
        this.scene.clear();
    }
}
