import * as THREE from "three";
import { ClothSolver } from "./cloth.js";
import { garmentProjectionGLSL } from "./garment-guide.js";

// Runtime mode integrates current/history poses; review mode bakes at 60 Hz.
// Only the cached review mode is independent of seek/playback history.
export function createSecondaryMotion(vrm, group) {
    const manager = vrm.springBoneManager;
    let cloth = null;
    const proxies = [];
    let cage = null;
    let cageObject = null;
    vrm.scene.traverse((object) => {
        if (object.userData.dollfightCage) {
            cage = object.userData.dollfightCage;
            cageObject = object;
        }
    });
    const cageBones = cage
        ? cage.rest.map((_, i) =>
              vrm.scene.getObjectByName(
                  `DF_Cage_${Math.floor(i / cage.segments)}_${i % cage.segments}`,
              ),
          )
        : [];
    if (cage)
        cloth = new ClothSolver(cage.rest.flat(), cage.segments, cage.rows, {
            shapeCorrective: true,
        });
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
        ["leftUpperLeg", "leftLowerLeg", cage?.capsuleRadii[0] ?? 0.067],
        ["rightUpperLeg", "rightLowerLeg", cage?.capsuleRadii[1] ?? 0.067],
        ["leftLowerLeg", "leftFoot", cage?.capsuleRadii[2] ?? 0.04],
        ["rightLowerLeg", "rightFoot", cage?.capsuleRadii[3] ?? 0.04],
    ];
    const surfaceContacts = [];
    cageObject?.traverse((mesh) => {
        if (!mesh.isSkinnedMesh) return;
        const uniforms = {
            dfLegA: {
                value: Array.from({ length: 4 }, () => new THREE.Vector4()),
            },
            dfLegB: {
                value: Array.from({ length: 4 }, () => new THREE.Vector4()),
            },
            dfWorldToLocal: { value: new THREE.Matrix4() },
            dfContactEnabled: { value: 1 },
        };
        const original = mesh.material;
        const material = original.clone();
        material.onBeforeCompile = (shader) => {
            Object.assign(shader.uniforms, uniforms);
            shader.vertexShader =
                `uniform vec4 dfLegA[4];\nuniform vec4 dfLegB[4];\nuniform mat4 dfWorldToLocal;\nuniform float dfContactEnabled;\n` +
                shader.vertexShader;
            shader.vertexShader = shader.vertexShader.replace(
                "#include <skinning_vertex>",
                "#include <skinning_vertex>\nif (dfContactEnabled > .5) {\n" +
                    garmentProjectionGLSL +
                    "\n}",
            );
        };
        material.customProgramCacheKey = () =>
            `dollfight-bounded-garment-contact-v3-${cage.rest.length}`;
        mesh.material = material;
        surfaceContacts.push({ mesh, uniforms });
    });
    let cache = null;
    let mode = "cache",
        liveTime = null,
        liveAccumulator = 0,
        stepMs = 0,
        lastDraw = null,
        lastEnabled = true;
    const localInverse = new THREE.Matrix4(),
        hipInverse = new THREE.Matrix4();
    function drawCloth(positions, worldSpace = false) {
        group.updateMatrixWorld(true);
        localInverse.copy(group.matrixWorld).invert();
        if (cage) {
            hipInverse.copy(hips.matrixWorld).invert();
            cageBones.forEach((bone, i) => {
                vector.fromArray(positions, i * 3);
                if (!worldSpace) vector.applyMatrix4(group.matrixWorld);
                bone.position.copy(vector.applyMatrix4(hipInverse));
            });
        } else {
            for (const proxy of proxies) {
                const attr = proxy.geometry.attributes.position;
                if (worldSpace) {
                    for (let i = 0; i < positions.length; i += 3)
                        vector
                            .fromArray(positions, i)
                            .applyMatrix4(localInverse)
                            .toArray(attr.array, i);
                } else attr.array.set(positions);
                attr.needsUpdate = true;
            }
            // Both materials share the same surface, so calculate normals once.
            if (proxies.length) {
                proxies[0].geometry.computeVertexNormals();
                for (const proxy of proxies.slice(1)) {
                    proxy.geometry.attributes.normal.array.set(
                        proxies[0].geometry.attributes.normal.array,
                    );
                    proxy.geometry.attributes.normal.needsUpdate = true;
                }
            }
        }
    }
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
    function updateSurfaceContacts(enabled) {
        if (!surfaceContacts.length) return;
        const contacts = capsules();
        for (const { mesh, uniforms } of surfaceContacts) {
            uniforms.dfContactEnabled.value = enabled ? 1 : 0;
            uniforms.dfWorldToLocal.value.copy(mesh.matrixWorld).invert();
            contacts.forEach((c, i) => {
                uniforms.dfLegA.value[i].set(...c.a, c.radius);
                uniforms.dfLegB.value[i].set(...c.b, 0);
            });
        }
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
        signature: JSON.stringify({
            cloth: cloth ? Array.from(cloth.rest) : null,
            springs: springBones.map((bone, i) => [
                bone.name,
                bone.position.toArray(),
                binds[i].toArray(),
            ]),
            capsules: bodyCapsules,
        }),
        setMode(value) {
            if (value !== mode) {
                mode = value;
                liveTime = null;
                lastDraw = null;
            }
        },
        get stats() {
            return {
                mode,
                stepMs,
                simulatedVertices: cloth?.rest.length / 3 || 0,
                gpuCage: !!cage,
                denseSurfaceProjection: surfaceContacts.length > 0,
            };
        },
        get enabled() {
            return !!cloth || springBones.length > 0;
        },
        get cache() {
            return cache;
        },
        useCache(value) {
            cache = value;
            lastDraw = null;
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
            if (mode === "live") {
                if (enabled !== lastEnabled) liveTime = null;
                lastEnabled = enabled;
                const started = performance.now();
                const dt = liveTime === null ? 0 : time - liveTime;
                group.updateMatrixWorld(true);
                if (liveTime === null || dt < 0 || dt > 0.1) {
                    liveAccumulator = 0;
                    manager?.reset();
                    if (cloth) {
                        const anchors = transformedRest(),
                            body = capsules();
                        cloth.reset(anchors);
                        // Initialize at the currently requested pose on seek;
                        // a raised leg must not start inside a vertical skirt.
                        for (let k = 0; k < 6; k++)
                            cloth.step(1 / 60, anchors, body);
                    }
                } else if (dt > 1e-6 && enabled) {
                    // Fixed 60 Hz simulation with 240 Hz contact substeps.
                    // ceil(renderDelta * 60) used to oversample a 50 Hz render
                    // loop and create a CPU slowdown feedback loop.
                    liveAccumulator += dt;
                    const steps = Math.min(
                        6,
                        Math.floor((liveAccumulator + 1e-9) * 60),
                    );
                    liveAccumulator -= steps / 60;
                    const anchors = cloth ? transformedRest() : null;
                    const body = cloth ? capsules() : null;
                    for (let k = 0; k < steps; k++) {
                        manager?.update(1 / 60);
                        if (cloth) cloth.step(1 / 60, anchors, body);
                    }
                }
                liveTime = time;
                updateSurfaceContacts(enabled);
                if (!enabled)
                    springBones.forEach((bone, i) =>
                        bone.quaternion.copy(binds[i]),
                    );
                if (cloth)
                    drawCloth(
                        enabled ? cloth.position : transformedRest(),
                        true,
                    );
                stepMs = performance.now() - started;
                return;
            }
            if (!cache) return;
            updateSurfaceContacts(enabled);
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
                if (lastDraw !== time || !enabled || cage) {
                    const positions =
                        baseline ||
                        Float32Array.from(
                            a.cloth,
                            (v, i) => v * (1 - alpha) + b.cloth[i] * alpha,
                        );
                    drawCloth(positions);
                    lastDraw = time;
                }
            }
        },
    };
}
