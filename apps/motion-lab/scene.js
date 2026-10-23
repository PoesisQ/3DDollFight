import * as THREE from "three";
import { OrbitControls } from "./vendor/OrbitControls.js";
import { configureOffAxis, configureOpponentCamera } from "./projection.js";
import { createAvatar, createStick } from "./avatar.js";
import { createVRMAvatar } from "./vrm-avatar.js";
import { CombatVisuals } from "./combat-visuals.js";

function renderer(container) {
    const instance = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    instance.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    instance.shadowMap.enabled = true;
    instance.shadowMap.type = THREE.PCFSoftShadowMap;
    instance.outputColorSpace = THREE.SRGBColorSpace;
    instance.toneMapping = THREE.ACESFilmicToneMapping;
    instance.toneMappingExposure = 1.0;
    container.appendChild(instance.domElement);
    return instance;
}

function environment(arena = false) {
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#16232b");
    scene.fog = new THREE.Fog("#16232b", 9, 22);
    scene.add(new THREE.HemisphereLight("#d2e9ec", "#526368", 0.7));
    const light = new THREE.DirectionalLight("#fff1df", 1.1);
    light.position.set(-2, 6, 4);
    light.castShadow = true;
    light.shadow.mapSize.set(1024, 1024);
    light.shadow.camera.left = -5;
    light.shadow.camera.right = 5;
    light.shadow.camera.top = 5;
    light.shadow.camera.bottom = -5;
    light.shadow.bias = -0.001;
    scene.add(light);
    const rim = new THREE.DirectionalLight("#76e3ca", 0.65);
    rim.position.set(0, 3, -5);
    scene.add(rim);
    const floor = new THREE.Mesh(
        new THREE.PlaneGeometry(40, 40),
        new THREE.MeshStandardMaterial({ color: "#24343e", roughness: 0.95 }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.035;
    floor.receiveShadow = true;
    scene.add(floor);
    const grid = new THREE.GridHelper(18, 36, "#496268", "#30434e");
    grid.position.y = -0.025;
    scene.add(grid);
    if (arena) {
        const platform = new THREE.Mesh(
            new THREE.BoxGeometry(5.8, 0.1, 3.7),
            new THREE.MeshStandardMaterial({
                color: "#35454d",
                roughness: 0.8,
            }),
        );
        platform.position.y = -0.09;
        platform.receiveShadow = true;
        scene.add(platform);
        const lineMaterial = new THREE.MeshBasicMaterial({ color: "#76e3ca" });
        for (const z of [-1.7, 1.7]) {
            const stripe = new THREE.Mesh(
                new THREE.BoxGeometry(5.6, 0.008, 0.018),
                lineMaterial,
            );
            stripe.position.set(0, -0.031, z);
            scene.add(stripe);
        }
        const circle = new THREE.Mesh(
            new THREE.RingGeometry(0.85, 0.87, 64),
            new THREE.MeshBasicMaterial({
                color: "#6b8588",
                side: THREE.DoubleSide,
            }),
        );
        circle.rotation.x = -Math.PI / 2;
        circle.position.y = -0.029;
        scene.add(circle);
        const back = new THREE.Mesh(
            new THREE.BoxGeometry(8, 3.2, 0.15),
            new THREE.MeshStandardMaterial({
                color: "#1a2932",
                roughness: 0.9,
            }),
        );
        back.position.set(0, 1.4, -3.3);
        scene.add(back);
        for (let i = -4; i <= 4; i++) {
            const pillar = new THREE.Mesh(
                new THREE.BoxGeometry(0.035, 2.4, 0.05),
                new THREE.MeshBasicMaterial({
                    color: i % 2 ? "#345059" : "#537772",
                }),
            );
            pillar.position.set(i * 0.8, 1.2, -3.19);
            scene.add(pillar);
        }
        for (const x of [-3, 3]) {
            const block = new THREE.Mesh(
                new THREE.BoxGeometry(0.55, 1.4, 0.5),
                new THREE.MeshStandardMaterial({ color: "#314750" }),
            );
            block.position.set(x, 0.65, -2);
            scene.add(block);
        }
    }
    return scene;
}

export class LabScene {
    constructor() {
        this.containers = ["main-view", "eye-one", "eye-two"].map((id) =>
            document.getElementById(id),
        );
        this.renderers = this.containers.map(renderer);
        this.arena = environment(true);
        this.combatVisuals = new CombatVisuals(this.arena);
        this.compare = environment(false);
        this.camera = new THREE.PerspectiveCamera(39, 1, 0.05, 50);
        this.camera.position.set(3.5, 2.4, 5.5);
        this.orbit = new OrbitControls(
            this.camera,
            this.renderers[0].domElement,
        );
        this.orbit.target.set(0, 0.9, 0);
        this.orbit.enableDamping = true;
        this.orbit.minDistance = 2;
        this.orbit.maxDistance = 12;
        this.orbit.maxPolarAngle = Math.PI * 0.48;
        this.eyeCameras = [
            new THREE.PerspectiveCamera(),
            new THREE.PerspectiveCamera(),
        ];
        this.mode = "retarget";
        this.followCenter = new THREE.Vector3();
        this.avatars = [];
        this.sticks = [];
        this.size();
        new ResizeObserver(() => this.size()).observe(this.containers[0]);
    }
    size() {
        this.containers.forEach((element, i) => {
            this.renderers[i].setSize(
                element.clientWidth,
                element.clientHeight,
                false,
            );
        });
        this.camera.aspect =
            this.containers[0].clientWidth / this.containers[0].clientHeight;
        this.camera.updateProjectionMatrix();
    }
    async prepareAvatar(buffer, opponentBuffer = buffer) {
        const avatars = [];
        try {
            for (let i = 0; i < 3; i++)
                avatars.push(
                    await createVRMAvatar(i === 1 ? opponentBuffer : buffer),
                );
            // Current duel frames share one target skeleton. The two generated
            // Liz assets intentionally use the same rest rig; reject an accidental
            // replacement with different proportions instead of silently distorting P2.
            if (
                avatars[0].rest.some((p, i) =>
                    p.some(
                        (v, j) => Math.abs(v - avatars[1].rest[i][j]) > 1e-4,
                    ),
                )
            )
                throw new Error(
                    "当前双人回放需要共享骨架比例；请单模型检查不同骨长的皮套",
                );
        } catch (error) {
            avatars.forEach((a) => a.dispose());
            throw error;
        }
        this.pendingAvatars?.forEach((a) => a.dispose());
        this.pendingAvatars = avatars;
        return {
            rest: avatars[0].rest,
            info:
                avatars[0].info +
                (opponentBuffer !== buffer ? " / P2：" + avatars[1].info : ""),
        };
    }
    load(run) {
        this.avatars.forEach((a) => {
            a.group.removeFromParent();
            a.dispose();
        });
        this.sticks.forEach((a) => {
            a.group.removeFromParent();
            a.dispose();
        });
        this.run = run;
        this.avatars = this.pendingAvatars || [
            createAvatar(run.target_rest, run.parents),
            createAvatar(run.target_rest, run.parents, "#ed8a78"),
            createAvatar(run.target_rest, run.parents),
        ];
        this.pendingAvatars = null;
        const [p1, p2, target] = this.avatars;
        p1.group.rotation.y = Math.PI / 2;
        p2.group.rotation.y = -Math.PI / 2;
        this.arena.add(
            p1.group,
            p2.group,
            p1.skeletonHelper,
            p2.skeletonHelper,
        );
        this.compare.add(target.group, target.skeletonHelper);
        this.sticks = [
            createStick("#e1bb70", run.parents),
            createStick("#76e3ca", run.parents),
        ];
        this.compare.add(...this.sticks.map((s) => s.group));
        this.setMode(this.mode);
    }
    setMode(mode) {
        this.mode = mode;
        this.followCenter.set(0, 0, 0);
        if (mode === "arena") this.camera.position.set(2.5, 1.9, 4.8);
        else if (mode === "avatar") this.camera.position.set(0, 1.1, 2.9);
        else
            this.camera.position.set(
                0.15,
                1.6,
                mode === "retarget" ? 4.5 : 6.1,
            );
        this.orbit.target.set(0, 0.88, 0);
        this.orbit.update();
        if (this.avatars.length) {
            this.sticks[0].group.visible = mode === "compare";
            this.sticks[1].group.visible = mode !== "avatar";
            this.sticks[0].group.position.x = -1.95;
            this.sticks[1].group.position.x = mode === "retarget" ? -1.5 : 0;
            this.avatars[2].group.position.x =
                mode === "avatar" ? 0 : mode === "retarget" ? 1.5 : 1.95;
        }
    }
    eye(index, frame, options, alpha) {
        const camera = this.eyeCameras[index],
            side = index === 0 ? 1 : -1;
        const right = new THREE.Vector3(0, 0, side),
            up = new THREE.Vector3(0, 1, 0);
        const { duel, nextDuel, offaxis, eyeOffset } = options;
        const eye = new THREE.Vector3()
            .fromArray(duel.world[index][4])
            .lerp(
                new THREE.Vector3().fromArray(nextDuel.world[index][4]),
                alpha,
            );
        eye.x += side * 0.09;
        eye.y += 0.025;
        eye.addScaledVector(right, eyeOffset);
        // Physical screen distance uses station-space head tracking, independent
        // of virtual movement gain. Turning the body does not rotate the screen.
        const physical = frame.solved[4].map(
            (v, i) => v - this.run.source_rest[4][i],
        );
        const distance = THREE.MathUtils.clamp(1.15 - physical[2], 0.35, 2);
        const center = eye
            .clone()
            .add(new THREE.Vector3(side * distance, 0, 0))
            .addScaledVector(right, physical[0] - eyeOffset)
            .addScaledVector(up, -physical[1]);
        const aspect =
            this.containers[index + 1].clientWidth /
            this.containers[index + 1].clientHeight;
        camera.position.copy(eye);
        camera.near = 0.04;
        camera.far = 35;
        if (offaxis) {
            const width = 0.78,
                h = width / aspect;
            const a = center
                .clone()
                .addScaledVector(right, -width / 2)
                .addScaledVector(up, -h / 2);
            const b = center
                .clone()
                .addScaledVector(right, width / 2)
                .addScaledVector(up, -h / 2);
            const c = center
                .clone()
                .addScaledVector(right, -width / 2)
                .addScaledVector(up, h / 2);
            configureOffAxis(camera, eye, a, b, c, camera.near, camera.far);
        } else {
            const target = duel.world[1 - index].map((p, j) =>
                p.map((v, k) =>
                    THREE.MathUtils.lerp(
                        v,
                        nextDuel.world[1 - index][j][k],
                        alpha,
                    ),
                ),
            );
            configureOpponentCamera(camera, eye, target, aspect);
        }
        camera.updateMatrixWorld(true);
    }
    draw(frame, next, alpha, second, nextSecond, options) {
        if (!this.run) return;
        this.orbit.update();
        for (let i = 0; i < 2; i++) {
            this.avatars[i].group.position
                .fromArray(options.duel.positions[i])
                .lerp(
                    new THREE.Vector3().fromArray(
                        options.nextDuel.positions[i],
                    ),
                    alpha,
                );
            this.avatars[i].group.rotation.y =
                i === 0 ? Math.PI / 2 : -Math.PI / 2;
        }
        this.avatars[0].apply(frame, next, alpha);
        this.avatars[1].apply(second, nextSecond, alpha);
        this.avatars[2].apply(frame, next, alpha);
        const audit = this.avatars[2].audit?.(frame, next, alpha);
        if (audit) {
            const worst = audit.reduce((a, b) => (a.error > b.error ? a : b));
            document.getElementById("mapping-audit").textContent =
                `实际蒙皮骨骼 / 求解目标：最大位置残差 ${worst.error.toFixed(1)} mm · ${worst.name}`;
        } else
            document.getElementById("mapping-audit").textContent =
                "几何人偶 · 直接使用 canonical19 骨架";
        // In the motion review, preserve captured root translation. Moving the
        // camera with the subjects keeps them in frame while the floor remains
        // stationary, so foot sliding is visible instead of hidden by in-place playback.
        if (this.mode !== "arena") {
            const motion = new THREE.Vector3(frame.root[0], 0, frame.root[2]);
            motion.lerp(
                new THREE.Vector3(next.root[0], 0, next.root[2]),
                alpha,
            );
            const sourceMotion = new THREE.Vector3(
                frame.solved[0][0],
                0,
                frame.solved[0][2],
            );
            this.avatars[2].group.position.set(
                (this.mode === "avatar"
                    ? 0
                    : this.mode === "retarget"
                      ? 1.15
                      : 1.95) + motion.x,
                0,
                motion.z,
            );
            this.sticks[0].group.position.set(
                -1.95 + sourceMotion.x,
                0,
                sourceMotion.z,
            );
            this.sticks[1].group.position.set(
                (this.mode === "retarget" ? -1.15 : 0) + sourceMotion.x,
                0,
                sourceMotion.z,
            );
            const center =
                this.mode === "avatar"
                    ? motion
                    : motion.clone().add(sourceMotion).multiplyScalar(0.5);
            const delta = center.clone().sub(this.followCenter);
            this.camera.position.add(delta);
            this.orbit.target.add(delta);
            this.followCenter.copy(center);
        }
        this.avatars.forEach((a) =>
            a.appearance(options.bones, options.wireframe),
        );
        this.sticks[0].apply(frame.raw, [], frame.solved[0]);
        this.sticks[1].apply(frame.solved, frame.quality, frame.solved[0]);
        this.combatVisuals.update(this.run, options, frame, second, alpha);
        this.renderers[0].render(
            this.mode === "arena" ? this.arena : this.compare,
            this.camera,
        );
        for (let i = 0; i < 2; i++) {
            this.eye(i, i === 0 ? frame : second, options, alpha);
            this.combatVisuals.debug.visible = false;
            this.avatars[i].group.visible = false;
            this.avatars[i].skeletonHelper.visible = false;
            this.renderers[i + 1].render(this.arena, this.eyeCameras[i]);
            this.avatars[i].group.visible = true;
            this.avatars[i].skeletonHelper.visible = options.bones;
        }
    }
}
