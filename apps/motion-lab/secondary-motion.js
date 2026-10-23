import * as THREE from "three";
import { ClothSolver } from "./cloth.js";

// Bake once at 60 Hz, then sample by animation time. Seeking, pausing, switching
// view and changing playback speed cannot change cloth/hair at a given time.
export function createSecondaryMotion(vrm, group) {
    const manager = vrm.springBoneManager;
    let cloth = null;
    const proxies = [];
    const garment = vrm.scene.getObjectByName("DollFight_PleatedSkirt");
    if (garment?.userData.dollfightCloth) {
        const sourceMeshes = [];
        garment.traverse((o) => {
            if (o.isSkinnedMesh) sourceMeshes.push(o);
        });
        const { segments, rows } = garment.userData.dollfightCloth;
        if (sourceMeshes.length) {
            cloth = new ClothSolver(
                sourceMeshes[0].geometry.attributes.position.array,
                segments,
                rows,
            );
            for (const original of sourceMeshes) {
                const geometry = original.geometry.clone();
                geometry.deleteAttribute("skinIndex");
                geometry.deleteAttribute("skinWeight");
                const mesh = new THREE.Mesh(geometry, original.material);
                mesh.name = "Simulated skirt surface";
                mesh.frustumCulled = false;
                mesh.castShadow = true;
                mesh.receiveShadow = true;
                original.visible = false;
                garment.add(mesh);
                proxies.push(mesh);
            }
            for (const joint of [...(manager?.joints || [])])
                if (joint.bone.name.startsWith("DF_Skirt_"))
                    manager.deleteJoint(joint);
        }
    }
    const springBones = [...(manager?.joints || [])].map((joint) => joint.bone);
    const binds = springBones.map((bone) => bone.quaternion.clone());
    const hips = vrm.humanoid.getRawBoneNode("hips");
    group.updateMatrixWorld(true);
    const inverseHipBind = hips.matrixWorld.clone().invert();
    const matrix = new THREE.Matrix4(),
        vector = new THREE.Vector3();
    const raw = (name) => vrm.humanoid.getRawBoneNode(name);
    const bodyCapsules = [
        ["leftUpperLeg", "leftLowerLeg", 0.103],
        ["rightUpperLeg", "rightLowerLeg", 0.103],
        ["leftLowerLeg", "leftFoot", 0.051],
        ["rightLowerLeg", "rightFoot", 0.051],
    ];
    let cache = null;
    function transformedRest() {
        matrix.copy(hips.matrixWorld).multiply(inverseHipBind);
        const array = new Float64Array(cloth.rest.length);
        for (let i = 0; i < array.length; i += 3)
            vector
                .fromArray(cloth.rest, i)
                .applyMatrix4(matrix)
                .toArray(array, i);
        return array;
    }
    function capsules() {
        return bodyCapsules.map(([a, b, radius]) => ({
            a: raw(a).getWorldPosition(new THREE.Vector3()).toArray(),
            b: raw(b).getWorldPosition(new THREE.Vector3()).toArray(),
            radius,
        }));
    }
    function snapshot() {
        const rotations = new Float32Array(springBones.length * 4);
        springBones.forEach((bone, i) =>
            bone.quaternion.toArray(rotations, i * 4),
        );
        return {
            rotations,
            cloth: cloth ? Float32Array.from(cloth.position) : null,
        };
    }
    const q = new THREE.Quaternion();
    return {
        proxies,
        get enabled() {
            return !!cloth || springBones.length > 0;
        },
        get cache() {
            return cache;
        },
        useCache(value) {
            cache = value;
        },
        async bake(frames, applyPose, progress = () => {}) {
            if (!frames.length || (!cloth && !springBones.length)) return;
            cache = null;
            const oldPosition = group.position.clone(),
                oldRotation = group.quaternion.clone();
            group.position.set(0, 0, 0);
            group.quaternion.identity();
            springBones.forEach((bone, i) => bone.quaternion.copy(binds[i]));
            applyPose(frames[0]);
            manager?.reset();
            if (cloth) cloth.reset(transformedRest());
            // Pre-roll the first pose to settle gravity without an initial pop.
            for (let k = 0; k < 30; k++) {
                applyPose(frames[0]);
                manager?.update(1 / 60);
                if (cloth) cloth.step(1 / 60, transformedRest(), capsules());
            }
            const samples = [snapshot()];
            const duration = frames.at(-1).t;
            let cursor = 0,
                maxStretch = 1,
                meanStretch = 0,
                worstStretch = null,
                worstContact = { maxPenetration: 0, fractionOver5mm: 0, t: 0 };
            for (let step = 1; step <= Math.ceil(duration * 60); step++) {
                const t = Math.min(step / 60, duration);
                while (
                    cursor + 1 < frames.length - 1 &&
                    frames[cursor + 1].t < t
                )
                    cursor++;
                const a = frames[cursor],
                    b = frames[Math.min(cursor + 1, frames.length - 1)];
                applyPose(a, b, b.t > a.t ? (t - a.t) / (b.t - a.t) : 0);
                manager?.update(1 / 60);
                if (cloth) {
                    cloth.step(1 / 60, transformedRest(), capsules());
                    const stretch = cloth.stretch();
                    if (stretch.max > maxStretch) {
                        maxStretch = stretch.max;
                        worstStretch = {
                            t,
                            ...stretch.worst,
                            capsules: capsules(),
                        };
                    }
                    meanStretch += stretch.mean;
                    const contact = cloth.collisionReport(capsules());
                    if (contact.maxPenetration > worstContact.maxPenetration)
                        worstContact = { ...contact, t };
                }
                samples.push(snapshot());
                if (step % 24 === 0) {
                    progress(Math.min(1, t / duration));
                    // MessageChannel yields without background-tab timer clamps.
                    await new Promise((resolve) => {
                        const channel = new MessageChannel();
                        channel.port1.onmessage = () => {
                            channel.port1.close();
                            channel.port2.close();
                            resolve();
                        };
                        channel.port2.postMessage(null);
                    });
                }
            }
            cache = {
                samples,
                duration,
                hz: 60,
                springBones: springBones.length,
                clothVertices: cloth ? cloth.rest.length / 3 : 0,
                maxStretch,
                worstStretch,
                worstContact,
                meanStretch: meanStretch / Math.max(1, samples.length - 1),
            };
            group.position.copy(oldPosition);
            group.quaternion.copy(oldRotation);
            return cache;
        },
        apply(time, enabled = true) {
            if (!cache) return;
            const at = Math.min(
                cache.samples.length - 1,
                Math.max(0, time * cache.hz),
            );
            const index = Math.floor(at),
                alpha = at - index;
            const a = cache.samples[index],
                b =
                    cache.samples[
                        Math.min(index + 1, cache.samples.length - 1)
                    ];
            springBones.forEach((bone, i) => {
                if (enabled)
                    bone.quaternion
                        .fromArray(a.rotations, i * 4)
                        .slerp(q.fromArray(b.rotations, i * 4), alpha);
                else bone.quaternion.copy(binds[i]);
            });
            if (cloth) {
                // The disabled control is the pelvis-attached cloth baseline.
                // Recompute in group-local coordinates (runtime group may face P2).
                let baseline;
                if (!enabled) {
                    group.updateMatrixWorld(true);
                    matrix
                        .copy(group.matrixWorld)
                        .invert()
                        .multiply(hips.matrixWorld)
                        .multiply(inverseHipBind);
                    baseline = new Float32Array(cloth.rest.length);
                    for (let i = 0; i < baseline.length; i += 3)
                        vector
                            .fromArray(cloth.rest, i)
                            .applyMatrix4(matrix)
                            .toArray(baseline, i);
                }
                for (const proxy of proxies) {
                    const attr = proxy.geometry.attributes.position;
                    for (let i = 0; i < attr.array.length; i++)
                        attr.array[i] = enabled
                            ? a.cloth[i] * (1 - alpha) + b.cloth[i] * alpha
                            : baseline[i];
                    attr.needsUpdate = true;
                    proxy.geometry.computeVertexNormals();
                }
            }
        },
    };
}
