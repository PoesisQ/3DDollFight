import * as THREE from "three";
import { GLTFLoader } from "./vendor/GLTFLoader.js";
import { VRMUtils } from "./vendor/three-vrm.module.min.js";
import { inspectEmbeddedGLB } from "./vrm-avatar.js";

// Unmodified free Tripo exports are useful for appearance inspection, even
// when their skeleton has been removed or collapsed by the export setting.
// Never silently fabricate a rig or make this static object mimic an animation.
export async function createStaticAvatar(buffer) {
    const doc = inspectEmbeddedGLB(buffer);
    const gltf = await new GLTFLoader().parseAsync(buffer.slice(0), "");
    const group = new THREE.Group();
    group.add(gltf.scene);
    group.updateMatrixWorld(true);
    const bounds = new THREE.Box3().setFromObject(gltf.scene);
    const size = bounds.getSize(new THREE.Vector3());
    if (!Number.isFinite(size.y) || size.y < 1e-6)
        throw new Error("静态模型没有有效身高");
    const scale = 1.65 / size.y;
    gltf.scene.scale.multiplyScalar(scale);
    gltf.scene.position.set(
        -((bounds.min.x + bounds.max.x) / 2) * scale,
        -bounds.min.y * scale,
        -((bounds.min.z + bounds.max.z) / 2) * scale,
    );
    group.updateMatrixWorld(true);
    const materials = [];
    gltf.scene.traverse((object) => {
        if (!object.isMesh) return;
        const original = Array.isArray(object.material)
            ? object.material
            : [object.material];
        const make = (Type) =>
            original.map(
                (source) =>
                    new Type({
                        map: source.map,
                        color: source.color,
                        side: source.side,
                        transparent: source.transparent,
                        opacity: source.opacity,
                        alphaTest: source.alphaTest,
                    }),
            );
        materials.push({
            object,
            original,
            matte: make(THREE.MeshLambertMaterial),
            texture: make(THREE.MeshBasicMaterial),
        });
    });
    return {
        group,
        static: true,
        headPoint: new THREE.Vector3(0, 1.53, 0),
        info: `Tripo H2.5 · 静态外观 · ${doc.skins?.length || 0} 个 skin 声明（非可用绑定）`,
        materialMode(mode) {
            for (const entry of materials) {
                const values = mode === "pbr" ? entry.original : entry[mode];
                entry.object.material =
                    values.length === 1 ? values[0] : values;
            }
        },
        dispose() {
            for (const entry of materials) {
                entry.object.material =
                    entry.original.length === 1
                        ? entry.original[0]
                        : entry.original;
                for (const material of [...entry.matte, ...entry.texture])
                    material.dispose();
            }
            VRMUtils.deepDispose(gltf.scene);
        },
    };
}
