import * as THREE from "three";
import { createVRMAvatar } from "./vrm-avatar.js";
import { createStaticAvatar } from "./static-avatar.js";

const $ = (id) => document.getElementById(id);
const cards = [],
    runs = new Map();
const baselineChoices = [
    ["old", "/assets/liz/nozomi.vrm"],
    ["nozomi", "/assets/atelier/nozomi.vrm"],
    ["mizore", "/assets/atelier/mizore.vrm"],
];
let loading = true;
const status = (value) => {
    $("status").textContent = value;
};
function staticFrame(avatar, t = 0) {
    return {
        t,
        root: [0, avatar.rest[0][1], 0],
        rotations: avatar.rest.map(() => [0, 0, 0, 1]),
        action_timing: null,
    };
}
function lighting(scene) {
    scene.background = new THREE.Color("#e7eeeb");
    scene.add(new THREE.HemisphereLight("#ffffff", "#c0c8c8", 1.8));
    const key = new THREE.DirectionalLight("#fff8f0", 2.0);
    key.position.set(-3, 5, 4);
    scene.add(key);
    const floor = new THREE.Mesh(
        new THREE.CircleGeometry(0.75, 64),
        new THREE.MeshBasicMaterial({ color: "#d5e0d9" }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.015;
    scene.add(floor);
}
function framePair(frames, t) {
    let i = 0;
    while (i + 1 < frames.length - 1 && frames[i + 1].t < t) i++;
    const a = frames[i],
        b = frames[Math.min(i + 1, frames.length - 1)];
    return [a, b, b.t > a.t ? (t - a.t) / (b.t - a.t) : 0];
}
function render() {
    if (loading) return;
    for (const c of cards) {
        const t = $("pose").value;
        if (c.avatar.static) c.avatar.materialMode($("material").value);
        if (!c.avatar.static) {
            c.avatar.secondary.useCache(
                t === "bind" ? c.bindCache : c.motionCache,
            );
            const [a, b, alpha] =
                t === "bind" || !c.motionReady
                    ? [staticFrame(c.avatar), null, 0]
                    : framePair(c.run.frames, +t);
            c.avatar.apply(a, b, alpha, $("cloth").checked);
        }
        c.scene.updateMatrixWorld(true);
        const head = c.avatar.static
            ? c.avatar.headPoint.clone()
            : c.avatar.vrm.humanoid
                  .getRawBoneNode("head")
                  .getWorldPosition(new THREE.Vector3());
        const close = $("crop").value === "face";
        const target = close
            ? head.clone().add(new THREE.Vector3(0, -0.015, 0))
            : new THREE.Vector3(0, 0.83, 0);
        const angle = {
            front: 0,
            three: 0.65,
            side: Math.PI / 2,
            back: Math.PI,
        }[$("angle").value];
        const distance = close ? 0.87 : 3.15;
        c.camera.position.set(
            target.x + Math.sin(angle) * distance,
            target.y + (close ? 0.06 : 0.12),
            target.z + Math.cos(angle) * distance,
        );
        c.camera.lookAt(target);
        c.camera.aspect = c.element.clientWidth / c.element.clientHeight;
        c.camera.updateProjectionMatrix();
        c.renderer.setSize(
            c.element.clientWidth,
            c.element.clientHeight,
            false,
        );
        c.renderer.render(c.scene, c.camera);
    }
    $("metrics").textContent = JSON.stringify(makeReport(), null, 2);
}
async function updatePose() {
    loading = true;
    $("pose").disabled = true;
    $("comparison").disabled = true;
    try {
        if ($("pose").value !== "bind")
            for (const c of cards) {
                if (c.motionReady || c.avatar.static) continue;
                status(`正在准备 ${c.id} 的真人动作与衣物缓存…`);
                const key = JSON.stringify(c.avatar.rest);
                if (!runs.has(key)) {
                    const response = await fetch("/api/run", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            source: "cmu_flow",
                            noise_mm: 0,
                            dropout: 0,
                            transition_blend: true,
                            target_rest: c.avatar.rest,
                        }),
                    });
                    const value = await response.json();
                    if (!response.ok) throw new Error(value.error);
                    runs.set(key, value);
                }
                c.run = runs.get(key);
                c.motionCache = await c.avatar.secondary.bake(
                    c.run.frames,
                    (a, b, alpha) => c.avatar.apply(a, b, alpha, true, true),
                    (p) =>
                        status(
                            `正在准备 ${c.id} 衣物回放 · ${Math.round(p * 100)}%`,
                        ),
                );
                c.motionReady = true;
            }
        status(
            $("pose").value === "bind"
                ? "绑定姿态 · 检查比例、轮廓与正侧背面"
                : "真人动捕关键帧 · 可动皮套使用同一时刻；Tripo 免费原件保持静态，未伪造绑定",
        );
    } catch (error) {
        status(`检查未完成：${error.message}`);
    } finally {
        loading = false;
        $("pose").disabled = false;
        $("comparison").disabled = false;
        render();
    }
}
async function start() {
    loading = true;
    $("pose").disabled = true;
    $("comparison").disabled = true;
    $("report").disabled = true;
    $("pose").value = "bind";
    for (const c of cards) {
        c.avatar.dispose();
        c.renderer.dispose();
        c.element.replaceChildren();
    }
    cards.length = 0;
    const mode = $("comparison").value;
    $("material-label").hidden = mode === "atelier";
    const character = mode.endsWith("mizore") ? "mizore" : "nozomi";
    const name = character === "nozomi" ? "希美" : "霙";
    const choices =
        mode === "atelier"
            ? baselineChoices
            : [
                  ["old", `/assets/liz/${character}.vrm`],
                  ["nozomi", `/assets/atelier/${character}.vrm`],
                  [
                      "mizore",
                      `/assets/tripo/${character === "nozomi" ? "nozomi-h25-retopo" : "mizore-h25-source"}.glb`,
                      true,
                  ],
              ];
    const labels =
        mode === "atelier"
            ? [
                  [
                      "旧路线",
                      "单图生成 + 规则绑定",
                      "正面投影 · 19 骨骼；裙摆与双腿混合蒙皮",
                  ],
                  [
                      "新底模 A",
                      "希美方向 · 外观草稿",
                      "完整 UV · 手指 / 扭转骨；独立裙布 + 腿部碰撞",
                  ],
                  [
                      "新底模 B",
                      "霙方向 · 外观草稿",
                      "同一可靠身体绑定；短发、白袜与校服变体",
                  ],
              ]
            : [
                  [
                      "旧路线",
                      `${name} · 旧单图方案`,
                      "规则权重与正面投影；保留作为失败对照",
                  ],
                  [
                      "可动底模",
                      `${name}方向 · 校服草稿`,
                      "可回放真人动作；脸型与发型还需精修",
                  ],
                  [
                      "Tripo 原件",
                      `${name} · H2.5 静态外观`,
                      "免费导出未含可用绑定；切动作时本列保持 T-pose",
                  ],
              ];
    for (const [i, [id, url, isStatic]] of choices.entries()) {
        const article = $(id).closest("article");
        article.querySelector(".badge").textContent = labels[i][0];
        article.querySelector("h2").textContent = labels[i][1];
        article.querySelector("p").textContent = labels[i][2];
        status(`正在加载 ${labels[i][1]}…`);
        const response = await fetch(url);
        if (!response.ok) throw new Error(`模型不可用：${id}`);
        const avatar = await (isStatic ? createStaticAvatar : createVRMAvatar)(
            await response.arrayBuffer(),
        );
        const scene = new THREE.Scene();
        lighting(scene);
        scene.add(avatar.group);
        const element = $(id),
            renderer = new THREE.WebGLRenderer({
                antialias: true,
                preserveDrawingBuffer: true,
            });
        renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.toneMapping = THREE.NeutralToneMapping;
        element.appendChild(renderer.domElement);
        const c = {
            id,
            avatar,
            scene,
            element,
            renderer,
            camera: new THREE.PerspectiveCamera(35, 1, 0.03, 20),
        };
        cards.push(c);
        if (!isStatic)
            c.bindCache = await avatar.secondary.bake(
                [staticFrame(avatar), staticFrame(avatar, 1)],
                (a, b, alpha) => avatar.apply(a, b, alpha, true, true),
            );
    }
    loading = false;
    status("绑定姿态 · 检查比例、轮廓与正侧背面");
    render();
    $("report").disabled = false;
    $("pose").disabled = false;
    $("comparison").disabled = false;
}
$("comparison").addEventListener("change", () => start().catch(showError));
$("pose").addEventListener("change", updatePose);
for (const id of ["angle", "crop", "cloth", "material"])
    $(id).addEventListener("change", render);
window.addEventListener("resize", render);
function makeReport() {
    return {
        pose: $("pose").value,
        angle: $("angle").value,
        secondary: $("cloth").checked,
        comparison: $("comparison").value,
        tripo_material_preview: $("material").value,
        visual_acceptance: "requires human review",
        models: cards.map((c) => ({
            id: c.id,
            name: c.avatar.info,
            static_only: !!c.avatar.static,
            cloth: c.motionCache
                ? {
                      hz: c.motionCache.hz,
                      vertices: c.motionCache.clothVertices,
                      max_constraint_length_ratio: c.motionCache.maxStretch,
                      worst_constraint: c.motionCache.worstStretch,
                      worst_capsule_contact: c.motionCache.worstContact,
                      mean_absolute_constraint_strain:
                          c.motionCache.meanStretch,
                  }
                : null,
        })),
    };
}
$("report").addEventListener("click", () => {
    const report = makeReport();
    const url = URL.createObjectURL(
        new Blob([JSON.stringify(report, null, 2)], {
            type: "application/json",
        }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "avatar-review.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
});
function showError(error) {
    status(`加载失败：${error.message}`);
    $("comparison").disabled = false;
}
start().catch(showError);
