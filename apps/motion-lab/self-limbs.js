import * as THREE from "./vendor/three.module.min.js";

// Build once, keep only triangles fully owned by a limb. Compact vertex buffers
// keep head, hair, torso and skirt out of the player pass without altering VRM
// materials, visibility, skeletons or the main arena's geometry.
export function limbGeometry(source, allowedBones) {
    const skin = source.getAttribute("skinIndex");
    const weights = source.getAttribute("skinWeight");
    if (!skin || !weights) return null;
    const keep = new Uint8Array(skin.count);
    for (let i = 0; i < skin.count; i++) {
        let influence = 0;
        for (let k = 0; k < 4; k++)
            if (allowedBones.has(skin.getComponent(i, k)))
                influence += weights.getComponent(i, k);
        keep[i] = influence >= 0.65;
    }
    const geometry = new THREE.BufferGeometry();
    const vertices = [],
        indices = [],
        remap = new Map();
    const count = source.index?.count ?? skin.count;
    const at = (i) => (source.index ? source.index.getX(i) : i);
    const groups = source.groups.length
        ? source.groups
        : [{ start: 0, count, materialIndex: 0 }];
    for (const group of groups) {
        const start = indices.length;
        for (
            let i = group.start;
            i < Math.min(count, group.start + group.count);
            i += 3
        ) {
            const triangle = [at(i), at(i + 1), at(i + 2)];
            if (!triangle.every((v) => keep[v])) continue;
            for (const v of triangle) {
                if (!remap.has(v)) {
                    remap.set(v, vertices.length);
                    vertices.push(v);
                }
                indices.push(remap.get(v));
            }
        }
        if (indices.length > start)
            geometry.addGroup(
                start,
                indices.length - start,
                group.materialIndex,
            );
    }
    if (!indices.length) return null;
    for (const [name, attribute] of Object.entries(source.attributes)) {
        const storage = attribute.isInterleavedBufferAttribute
            ? attribute.data.array
            : attribute.array;
        const array = new storage.constructor(
            vertices.length * attribute.itemSize,
        );
        // BufferAttribute getters normalize integers. Copy the stored values,
        // including quantized normals / weights, without a second normalization.
        for (let i = 0; i < vertices.length; i++)
            for (let k = 0; k < attribute.itemSize; k++)
                array[i * attribute.itemSize + k] =
                    attribute.isInterleavedBufferAttribute
                        ? attribute.data.array[
                              vertices[i] * attribute.data.stride +
                                  attribute.offset +
                                  k
                          ]
                        : attribute.array[vertices[i] * attribute.itemSize + k];
        geometry.setAttribute(
            name,
            new THREE.BufferAttribute(
                array,
                attribute.itemSize,
                attribute.normalized,
            ),
        );
    }
    geometry.setIndex(indices);
    return geometry;
}

// This matrix is used ONLY for presentation. The camera frames the whole
// opponent from farther back, so relocate the visible own limbs to the eye.
// Rotations, finger curl and relative joint motion remain the real avatar's.
export function selfViewTransform(camera, head) {
    const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(
        camera.quaternion,
    );
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(camera.quaternion);
    const offset = camera.position
        .clone()
        .sub(head)
        .addScaledVector(forward, 0.3)
        .addScaledVector(up, -0.08);
    return new THREE.Matrix4().makeTranslation(...offset.toArray());
}

export class SelfLimbs {
    constructor(avatar) {
        this.avatar = avatar;
        this.scene = new THREE.Scene();
        this.scene.add(new THREE.HemisphereLight("#d2e9ec", "#526368", 0.55));
        const key = new THREE.DirectionalLight("#fff1df", 0.85);
        key.position.set(-2, 6, 4);
        this.scene.add(key);
        const rim = new THREE.DirectionalLight("#76e3ca", 0.35);
        rim.position.set(0, 3, -5);
        this.scene.add(rim);
        this.camera = new THREE.PerspectiveCamera(68, 1, 0.045, 8);
        this.parts = [];
        this.materials = new Map();
        const viewMaterial = (source) => {
            if (!this.materials.has(source)) {
                // The generated avatars use unlit skin. In a close-up that
                // becomes a flat white silhouette, hiding the fingers. Shade
                // only this view's copy; keep the original texture and colour.
                const copy = source.isMeshBasicMaterial
                    ? new THREE.MeshStandardMaterial({
                          color: source.color,
                          map: source.map,
                          alphaMap: source.alphaMap,
                          alphaTest: source.alphaTest,
                          transparent: source.transparent,
                          opacity: source.opacity,
                          side: source.side,
                          vertexColors: source.vertexColors,
                          roughness: 0.9,
                          metalness: 0,
                      })
                    : source.clone();
                // When the body turns out of the eye view, don't expose a
                // hard shoulder / hip cross-section on the isolated limb.
                copy.transparent = true;
                copy.alphaTest = Math.max(copy.alphaTest, 0.02);
                copy.forceSinglePass = true;
                copy.onBeforeCompile = (shader) => {
                    shader.vertexShader =
                        "attribute float selfLimbFade;\nvarying float vSelfLimbFade;\n" +
                        shader.vertexShader;
                    shader.vertexShader = shader.vertexShader.replace(
                        "#include <begin_vertex>",
                        "#include <begin_vertex>\nvSelfLimbFade = selfLimbFade;",
                    );
                    shader.fragmentShader =
                        "varying float vSelfLimbFade;\n" +
                        shader.fragmentShader;
                    shader.fragmentShader = shader.fragmentShader.replace(
                        "#include <alphatest_fragment>",
                        "diffuseColor.a *= vSelfLimbFade;\n#include <alphatest_fragment>",
                    );
                };
                copy.customProgramCacheKey = () => "self-limb-root-fade-v1";
                this.materials.set(source, copy);
            }
            return this.materials.get(source);
        };
        const rootFor = (name, index) =>
            avatar.vrm
                ? avatar.vrm.humanoid.getRawBoneNode(name)
                : avatar.bones[index];
        for (const [name, index, foot] of [
            ["leftUpperArm", 5, null],
            ["rightUpperArm", 8, null],
            ["leftUpperLeg", 11, 13],
            ["rightUpperLeg", 15, 17],
        ]) {
            const nodes = new Set();
            rootFor(name, index)?.traverse((node) => {
                if (node.isBone) nodes.add(node);
            });
            const start = rootFor(name, index).getWorldPosition(
                new THREE.Vector3(),
            );
            const end = avatar.vrm
                ? avatar.vrm.humanoid
                      .getRawBoneNode(name.replace("Upper", "Lower"))
                      .getWorldPosition(new THREE.Vector3())
                : avatar.bones[index + 1].getWorldPosition(new THREE.Vector3());
            const axis = end.sub(start).normalize();
            avatar.group.traverse((source) => {
                if (!source.isSkinnedMesh) return;
                const allowed = new Set(
                    source.skeleton.bones.flatMap((bone, i) =>
                        nodes.has(bone) ? [i] : [],
                    ),
                );
                if (!allowed.size) return;
                const geometry = limbGeometry(source.geometry, allowed);
                if (!geometry) return;
                const position = geometry.getAttribute("position");
                const fade = new Float32Array(position.count);
                const vertex = new THREE.Vector3();
                for (let i = 0; i < fade.length; i++) {
                    vertex
                        .fromBufferAttribute(position, i)
                        .applyMatrix4(source.matrixWorld)
                        .sub(start);
                    fade[i] = THREE.MathUtils.smoothstep(
                        vertex.dot(axis),
                        foot === null ? 0.025 : 0.06,
                        foot === null ? 0.15 : 0.22,
                    );
                }
                geometry.setAttribute(
                    "selfLimbFade",
                    new THREE.BufferAttribute(fade, 1),
                );
                const material = Array.isArray(source.material)
                    ? source.material.map(viewMaterial)
                    : viewMaterial(source.material);
                const mesh = new THREE.SkinnedMesh(geometry, material);
                mesh.bind(source.skeleton, source.bindMatrix);
                mesh.bindMode = "detached";
                mesh.matrixAutoUpdate = false;
                mesh.frustumCulled = false;
                // Mesh.updateMatrixWorld normally replaces bindMatrixInverse.
                // Preserve the source's inverse; applying the display offset to
                // both matrices would cancel it and put the hands back far away.
                mesh.onBeforeRender = () =>
                    mesh.bindMatrixInverse.copy(source.bindMatrixInverse);
                this.scene.add(mesh);
                this.parts.push({ mesh, source, foot });
            });
        }
    }
    draw(renderer, viewCamera, physicalEye = false) {
        if (!this.parts.length) return;
        const camera = this.camera;
        camera.position.copy(viewCamera.position);
        camera.quaternion.copy(viewCamera.quaternion);
        camera.aspect = viewCamera.aspect;
        camera.updateProjectionMatrix();
        if (physicalEye) {
            camera.projectionMatrix.copy(viewCamera.projectionMatrix);
            camera.projectionMatrixInverse.copy(
                viewCamera.projectionMatrixInverse,
            );
        }
        camera.updateMatrixWorld(true);
        const head = this.avatar.bones[4].getWorldPosition(new THREE.Vector3());
        const transform = physicalEye
            ? new THREE.Matrix4()
            : selfViewTransform(camera, head);
        for (const { mesh, source, foot } of this.parts) {
            // Normal walking feet stay below the viewport. A lifted attacking
            // leg enters from below, including its preparation and recovery.
            const lift =
                foot === null
                    ? 1
                    : this.avatar.bones[foot].getWorldPosition(
                          new THREE.Vector3(),
                      ).y;
            mesh.visible = source.visible && (foot === null || lift > 0.32);
            mesh.matrix.multiplyMatrices(transform, source.matrixWorld);
            mesh.bindMatrix.copy(source.bindMatrix);
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
        // Skeletons and textures belong to the original avatar.
        for (const { mesh } of this.parts) mesh.geometry.dispose();
        for (const material of this.materials.values()) material.dispose();
        this.scene.clear();
    }
}
