import * as THREE from "three";
import { GLTFLoader } from "./vendor/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils } from "./vendor/three-vrm.module.min.js";

export const HUMAN_BONES = [
    "hips",
    "spine",
    "chest",
    "neck",
    "head",
    "leftUpperArm",
    "leftLowerArm",
    "leftHand",
    "rightUpperArm",
    "rightLowerArm",
    "rightHand",
    "leftUpperLeg",
    "leftLowerLeg",
    "leftFoot",
    "leftToes",
    "rightUpperLeg",
    "rightLowerLeg",
    "rightFoot",
    "rightToes",
];
const PARENTS = [
    -1, 0, 1, 2, 3, 2, 5, 6, 2, 8, 9, 0, 11, 12, 13, 0, 15, 16, 17,
];

export function inspectVRM(buffer) {
    if (buffer.byteLength > 40 * 1024 * 1024) throw new Error("VRM 超过 40 MB");
    const v = new DataView(buffer);
    if (v.getUint32(0, true) !== 0x46546c67 || v.getUint32(4, true) !== 2)
        throw new Error("需要二进制 VRM / GLB 2.0 文件");
    if (v.getUint32(16, true) !== 0x4e4f534a)
        throw new Error("VRM 缺少 JSON 块");
    const json = JSON.parse(
        new TextDecoder().decode(
            new Uint8Array(buffer, 20, v.getUint32(12, true)),
        ),
    );
    for (const item of [...(json.buffers || []), ...(json.images || [])])
        if (item.uri && !item.uri.startsWith("data:"))
            throw new Error("请使用资源内嵌的 VRM；不加载文件中的外部地址");
    if (!json.extensions?.VRMC_vrm && !json.extensions?.VRM)
        throw new Error("文件没有 VRM humanoid 扩展");
    return json;
}

export async function createVRMAvatar(buffer) {
    inspectVRM(buffer);
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const gltf = await loader.parseAsync(buffer.slice(0), "");
    const vrm = gltf.userData.vrm;
    if (!vrm) throw new Error("VRM 解析失败");
    VRMUtils.rotateVRM0(vrm);
    // Playback must be seekable: secondary spring simulation is not advanced
    // from wall time (otherwise a paused frame changes every time it is viewed).
    const group = new THREE.Group();
    group.add(vrm.scene);
    group.updateMatrixWorld(true);
    const bones = HUMAN_BONES.map((name) =>
        vrm.humanoid.getNormalizedBoneNode(name),
    );
    const missing = HUMAN_BONES.filter((_, i) => !bones[i]);
    if (missing.length) {
        VRMUtils.deepDispose(vrm.scene);
        throw new Error(
            `此检查器需要 19 个映射关节；缺少 ${missing.join(", ")}`,
        );
    }
    const rest = bones.map((bone) =>
        bone.getWorldPosition(new THREE.Vector3()).toArray(),
    );
    const bind = bones.map((bone) =>
        bone.getWorldQuaternion(new THREE.Quaternion()),
    );
    const skeletonHelper = new THREE.SkeletonHelper(
        vrm.humanoid.normalizedHumanBonesRoot,
    );
    skeletonHelper.material.depthTest = false;
    skeletonHelper.renderOrder = 10;
    const meshes = [];
    vrm.scene.traverse((o) => {
        if (o.isMesh) {
            o.frustumCulled = false;
            o.castShadow = true;
            o.receiveShadow = true;
            meshes.push(o);
        }
    });
    const globals = bones.map(() => new THREE.Quaternion());
    const q = new THREE.Quaternion(),
        parent = new THREE.Quaternion();
    const groupQ = new THREE.Quaternion(),
        desired = new THREE.Quaternion();
    const rootPosition = new THREE.Vector3();
    const fingers = [];
    for (const side of ["left", "right"])
        for (const finger of ["Index", "Middle", "Ring", "Little"])
            for (const segment of ["Proximal", "Intermediate", "Distal"]) {
                const node = vrm.humanoid.getNormalizedBoneNode(
                    side + finger + segment,
                );
                if (node)
                    fingers.push({
                        node,
                        bind: node.quaternion.clone(),
                        sign: side === "left" ? -1 : 1,
                    });
            }
    return {
        group,
        bones,
        skeletonHelper,
        rest,
        vrm,
        info: `${vrm.meta.name || vrm.meta.title || "本地 VRM"} · ${bones.length}/19 关节 · ${meshes.length} 网格`,
        audit(frame, next, alpha = 0) {
            const inverse = group.matrixWorld.clone().invert();
            // Compare against FK of the SAME interpolated rotations, not
            // linearly interpolated joint positions (a rotating bone follows
            // an arc, which otherwise creates a false binding error).
            const expectedPoints = [],
                expectedRotations = [];
            for (let i = 0; i < HUMAN_BONES.length; i++) {
                const rotation = new THREE.Quaternion().fromArray(
                    frame.rotations[i],
                );
                if (next)
                    rotation.slerp(
                        new THREE.Quaternion().fromArray(next.rotations[i]),
                        alpha,
                    );
                const parentIndex = PARENTS[i];
                expectedRotations[i] =
                    parentIndex < 0
                        ? rotation
                        : rotation.premultiply(expectedRotations[parentIndex]);
                expectedPoints[i] =
                    parentIndex < 0
                        ? new THREE.Vector3(
                              0,
                              THREE.MathUtils.lerp(
                                  frame.root[1],
                                  next?.root[1] ?? frame.root[1],
                                  alpha,
                              ),
                              0,
                          )
                        : new THREE.Vector3(...rest[i])
                              .sub(new THREE.Vector3(...rest[parentIndex]))
                              .applyQuaternion(expectedRotations[parentIndex])
                              .add(expectedPoints[parentIndex]);
            }
            return HUMAN_BONES.map((name, i) => {
                const actual = vrm.humanoid
                    .getRawBoneNode(name)
                    .getWorldPosition(new THREE.Vector3())
                    .applyMatrix4(inverse);
                return {
                    name,
                    error: actual.distanceTo(expectedPoints[i]) * 1000,
                };
            });
        },
        apply(frame, next, alpha = 0) {
            group.updateMatrixWorld(true);
            group.getWorldQuaternion(groupQ);
            // Canonical local rotations cannot be assigned directly to VRM:
            // it has extra shoulder / upperChest nodes and its own bind axes.
            bones.forEach((bone, i) => {
                q.fromArray(frame.rotations[i]);
                if (next)
                    q.slerp(
                        new THREE.Quaternion().fromArray(next.rotations[i]),
                        alpha,
                    );
                globals[i].copy(q);
                if (PARENTS[i] >= 0)
                    globals[i].premultiply(globals[PARENTS[i]]);
                desired.copy(groupQ).multiply(globals[i]).multiply(bind[i]);
                bone.parent.getWorldQuaternion(parent);
                bone.quaternion.copy(parent.invert()).multiply(desired);
                if (i === 0) {
                    rootPosition.set(
                        0,
                        THREE.MathUtils.lerp(
                            frame.root[1],
                            next?.root[1] ?? frame.root[1],
                            alpha,
                        ),
                        0,
                    );
                    group.localToWorld(rootPosition);
                    bone.position.copy(bone.parent.worldToLocal(rootPosition));
                }
                bone.updateWorldMatrix(false, true);
            });
            // Hand shape is a display prior: canonical19 contains no fingers.
            // Keep defence open; close the four fingers during recorded kicks / attacks.
            const closed =
                frame.action_timing && frame.action_timing.phase !== "ready";
            for (const finger of fingers)
                finger.node.quaternion
                    .copy(finger.bind)
                    .multiply(
                        q.setFromAxisAngle(
                            new THREE.Vector3(0, 0, 1),
                            closed ? finger.sign * 0.85 : 0.12 * finger.sign,
                        ),
                    );
            vrm.humanoid.update();
            vrm.expressionManager?.update();
            vrm.nodeConstraintManager?.update();
            group.updateMatrixWorld(true);
        },
        appearance(showBones, wireframe) {
            skeletonHelper.visible = showBones;
            meshes.forEach((mesh) => {
                for (const mat of Array.isArray(mesh.material)
                    ? mesh.material
                    : [mesh.material])
                    mat.wireframe = wireframe;
            });
        },
        dispose() {
            skeletonHelper.removeFromParent();
            skeletonHelper.geometry.dispose();
            skeletonHelper.material.dispose();
            VRMUtils.deepDispose(vrm.scene);
        },
    };
}
