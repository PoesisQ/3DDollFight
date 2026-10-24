import { LabScene } from "./scene.js";
import { MatchRecorder } from "./match-recorder.js";

const $ = (id) => document.getElementById(id);
let scene,
    run,
    currentConfig,
    uploaded = null,
    playing = true,
    time = 0,
    last = performance.now();
let renderCount = 0,
    fpsTime = last,
    lastUi = 0;
let requestId = 0;
const recorder = new MatchRecorder();
let vrmBuffer = null,
    localBuffer = null,
    opponentBuffer = null,
    targetRest = null,
    avatarInfo = "";
const names = {
    left_arm: "左臂",
    right_arm: "右臂",
    left_leg: "左腿",
    right_leg: "右腿",
};
const phases = {
    ready: "就绪",
    preparation: "准备",
    committed: "提交",
    recovery: "回收",
    unreliable: "不可靠",
    defending: "防守",
    supporting: "全身协同",
};

function error(message) {
    $("error").textContent = message;
    $("error").hidden = false;
}
function download(name, text, type = "application/json") {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
}
function config() {
    const value = {
        source: $("source").value,
        transition_blend: $("transition-blend").checked,
        noise_mm: +$("noise").value,
        dropout: +$("dropout").value / 100,
        cutoff: +$("cutoff").value,
        smoothing: $("smoothing").checked,
        constraints: $("constraints").checked,
        foot_lock: $("foot-lock").checked,
        profile: $("profile").value,
        movement_enabled: $("movement-enabled").checked,
        movement_gain: +$("movement-gain").value,
        initial_gap: +$("initial-gap").value,
        seed: 42,
        target_rest:
            $("avatar-kind").value === "vrm"
                ? targetRest?.map((p) => p.map((v) => +v.toFixed(6)))
                : null,
    };
    if (value.source === "upload")
        Object.assign(value, {
            frames: uploaded,
            camera_height: +$("camera-height").value,
            camera_distance: +$("camera-distance").value,
        });
    return value;
}
async function compute({ preserveTime = false } = {}) {
    if (recorder.active) recorder.stop();
    const id = ++requestId;
    const previousTime = preserveTime ? time : 0;
    $("loading").hidden = false;
    $("apply").disabled = true;
    $("source").disabled = true;
    $("avatar-kind").disabled = true;
    $("avatar-asset").disabled = true;
    $("transition-blend").disabled = true;
    $("import-vrm").disabled = true;
    $("error").hidden = true;
    try {
        if ($("avatar-kind").value === "vrm") {
            if (!vrmBuffer) {
                const choice = $("avatar-asset").value;
                const atelier = choice.startsWith("atelier");
                const localRig = choice.startsWith("local-");
                const suffix = choice === "local-hybrid" ? "-hybrid" : "";
                const url = localRig
                    ? `/assets/local/nozomi${suffix}.vrm`
                    : choice === "sample"
                      ? "/assets/sample.vrm"
                      : atelier
                        ? `/assets/atelier/${choice === "atelier-mizore" ? "mizore" : "nozomi"}.vrm`
                        : `/assets/liz/${choice === "pair" ? "nozomi" : choice}.vrm`;
                const asset = await fetch(url);
                if (!asset.ok)
                    throw new Error(
                        choice === "sample"
                            ? "缺少样例：请运行 uv run python tools/fetch_avatar.py"
                            : "缺少角色文件：请先 git lfs pull，或导入本地 VRM",
                    );
                const primary = await asset.arrayBuffer();
                let opponent = null;
                if (choice === "pair" || choice === "atelier" || localRig) {
                    const other = await fetch(
                        localRig
                            ? `/assets/local/mizore${suffix}.vrm`
                            : `/assets/${atelier ? "atelier" : "liz"}/mizore.vrm`,
                    );
                    if (!other.ok)
                        throw new Error("缺少霙的 VRM：请先 git lfs pull");
                    opponent = await other.arrayBuffer();
                }
                vrmBuffer = primary;
                opponentBuffer = opponent;
            }
            const binding = await scene.prepareAvatar(
                vrmBuffer,
                opponentBuffer || vrmBuffer,
            );
            targetRest = binding.rest;
            avatarInfo = binding.info;
        } else {
            targetRest = null;
            avatarInfo = "程序几何人偶 · 用于骨长、权重与 IK 检查";
        }
        if (id !== requestId) return;
        $("profile").disabled = !!targetRest;
        $("avatar-status").textContent = avatarInfo;
        const nextConfig = config();
        const response = await fetch("/api/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(nextConfig),
        });
        const value = await response.json();
        if (id !== requestId) return;
        if (!response.ok) throw new Error(value.error || "处理失败");
        run = value;
        currentConfig = nextConfig;
        time = Math.min(previousTime, run.duration);
        await scene.load(run, $("secondary-mode").value);
        const cloth = scene.avatars[0].secondary?.cache;
        $("secondary-status").textContent =
            $("secondary-mode").value === "live"
                ? "实时逐帧：衣物只使用当前姿态；倒拖 / 大幅跳转会重置，不预读后续动作。"
                : cloth
                  ? `60 Hz 固定步长缓存 · ${cloth.springBones} 个衣发辅助骨 · ${cloth.clothVertices} 个裙布顶点；暂停、拖动与变速使用同一结果。`
                  : "此模型没有可计算的独立衣物 / 发丝结构。";
        buildCombatUI();
        last = performance.now();
        const m = run.metrics;
        $("metric-error").innerHTML =
            `${m.raw_error_mm}<b> → </b><em>${m.solved_error_mm}</em> <b>mm</b>`;
        $("metric-bone").innerHTML =
            `${m.raw_bone_error_mm.toFixed(1)}<b> → </b><em>${m.solved_bone_error_mm.toFixed(1)}</em> <b>mm</b>`;
        $("metric-time").innerHTML =
            `${m.processing_p95_ms.toFixed(1)} <b>ms</b>`;
        $("metric-events").innerHTML = `${m.event_count} <b>次 / 整段</b>`;
        $("metric-valid").textContent = `输入有效关节 ${m.observed_percent}%`;
        $("metric-reference").textContent =
            m.reference === "input_consistency_only"
                ? "相对导入数据的一致性，无三维真值"
                : "相对未加噪输入，非实机精度";
        if (run.evaluation_cache)
            $("metric-reference").textContent += " · 复用同配置回放计算";
        $("description").textContent = run.description;
        const composed = run.source === "cmu_composed_mocap";
        const assetCheck = run.source === "asset_bind_check";
        const actual = run.source === "cmu_optical_mocap" || composed,
            upload = run.source === "uploaded_poseframe";
        $("source-badge").textContent =
            nextConfig.source === "cmu_sparring"
                ? "真人动捕 · 三回合排练"
                : assetCheck
                  ? "静态绑定检查"
                  : composed
                    ? nextConfig.transition_blend
                        ? "真人片段 · 算法衔接"
                        : "真人片段 · 硬切对照"
                    : actual
                      ? "真实光学动捕"
                      : upload
                        ? "外部骨架输入"
                        : "合成验证";
        $("source-note").textContent = assetCheck
            ? "静态资产检查 · 不作为人体动作数据"
            : composed
              ? "不同动捕片段组合 · 过渡不是原始采集"
              : actual
                ? "CMU 光学动捕 · 独立显示规则识别结果"
                : upload
                  ? "外部输入 · 无独立三维真值"
                  : "合成验证 · 不是摄像头实测";
        const fragment = document.createDocumentFragment();
        for (const event of run.events) {
            const button = document.createElement("button");
            button.dataset.event = event.id;
            button.append(document.createTextNode(event.label));
            const timestamp = document.createElement("span");
            timestamp.textContent = `${event.time_s.toFixed(2)} s`;
            button.append(timestamp);
            button.addEventListener("click", () => {
                time = Math.max(0, event.time_s - 0.12);
                setPlaying(false);
            });
            fragment.append(button);
        }
        $("events").replaceChildren(fragment);
        if (!run.events.length) {
            const p = document.createElement("p");
            p.className = "empty";
            p.textContent = "本段没有触发动作事件。静止负样本应保持这种状态。";
            $("events").append(p);
        }
        $("phase-list").replaceChildren();
        for (const [key, name] of Object.entries(names)) {
            const item = document.createElement("div");
            item.append(document.createTextNode(name));
            const state = document.createElement("b");
            state.id = `phase-${key}`;
            item.append(state);
            $("phase-list").append(item);
        }
        document.body.dataset.ready = "true";
    } catch (err) {
        if (id === requestId) error(err.message);
    } finally {
        if (id === requestId) {
            $("loading").hidden = true;
            $("apply").disabled = false;
            $("source").disabled = false;
            $("avatar-kind").disabled = false;
            $("avatar-asset").disabled = false;
            $("transition-blend").disabled = false;
            $("import-vrm").disabled = false;
        }
    }
}
function setPlaying(value) {
    playing = value;
    $("play").textContent = value ? "Ⅱ" : "▶";
    $("play").setAttribute("aria-label", value ? "暂停回放" : "播放回放");
}
function frameAt(t) {
    let low = 0,
        high = run.frames.length - 1;
    while (low < high) {
        const mid = Math.ceil((low + high) / 2);
        if (run.frames[mid].t <= t) low = mid;
        else high = mid - 1;
    }
    const index = low,
        next = Math.min(index + 1, run.frames.length - 1);
    const a = run.frames[index],
        b = run.frames[next];
    return [a, b, b.t > a.t ? (t - a.t) / (b.t - a.t) : 0, index];
}
function buildCombatUI() {
    const labels = Object.fromEntries(
        [
            ...run.events,
            ...run.duel.opponent_events,
            ...run.reference_actions,
        ].map((e) => [e.action, e.label]),
    );
    $("chapters").replaceChildren();
    for (const chapter of run.duel.chapters) {
        if (run.name === "cmu_sparring" && chapter.time_s % 30 !== 0) continue;
        const button = document.createElement("button");
        button.textContent =
            run.name === "cmu_sparring"
                ? `第 ${Math.floor(chapter.time_s / 30) + 1} 回合 · ${chapter.time_s}–${chapter.time_s + 30} 秒`
                : chapter.label;
        button.dataset.start = chapter.time_s;
        button.addEventListener("click", () => {
            time = chapter.time_s;
            setPlaying(true);
        });
        $("chapters").append(button);
    }
    $("combat-source").textContent = run.duel.description;
    $("combat-events").replaceChildren();
    for (const event of run.duel.events) {
        const button = document.createElement("button");
        button.dataset.result = event.id;
        button.dataset.outcome = event.outcome;
        const title = document.createElement("strong");
        title.textContent = `P${event.attacker + 1} → P${event.defender + 1} · ${event.label}`;
        const detail = document.createElement("span");
        detail.textContent = `${labels[event.action] || event.action} · ${event.time_s.toFixed(2)} s · ${event.damage ? `−${event.damage} HP${event.combo_count > 1 ? ` · ${event.combo_count} 连击` : ""}` : "无伤害"}`;
        button.append(title, detail);
        button.addEventListener("click", () => {
            time = event.time_s;
            setPlaying(false);
        });
        $("combat-events").append(button);
    }
}
function ui(frame, duel) {
    $("round-status").textContent =
        run.name === "cmu_sparring"
            ? `ROUND ${duel.round} / 3 · ${Math.ceil(30 - (duel.round_time || 0))} s`
            : "DOLLFIGHT";
    $("round-intent").textContent = duel.intent?.[0] || "真人动作回放";
    $("time").textContent =
        `${time.toFixed(2).padStart(5, "0")} / ${run.duration.toFixed(2)}`;
    $("timeline").value = Math.round((time / run.duration) * 1000);
    const latest = run.events.filter((e) => e.time_s <= time).at(-1);
    const otherTime = (run.duel.opponent_frames || run.frames)[
        duel.opponent_frame
    ].t;
    const otherLatest = run.duel.opponent_events
        .filter((e) => e.time_s <= otherTime)
        .at(-1);
    $("action-label").textContent =
        `P1 · ${latest && time - latest.time_s < 0.9 ? latest.label : "待机"} / P2 · ${otherLatest && otherTime - otherLatest.time_s < 0.9 ? otherLatest.label : "待机"}`;
    const counts = frame.quality.reduce((a, q) => {
        a[q] = (a[q] || 0) + 1;
        return a;
    }, {});
    $("quality-label").textContent =
        `${counts.observed || 0}/19 可靠 · ${counts.predicted || 0} 预测 · ${counts.missing || 0} 缺失`;
    $("state-label").textContent = frame.recognition.state;
    const body = frame.body;
    if (body)
        $("body-readout").textContent =
            `髋肩扭转 ${body.hip_chest_deg.toFixed(0)}° · 躯干倾斜 ${body.lean_deg.toFixed(0)}° · ${body.support}`;
    const timing = frame.action_timing;
    $("action-timing").textContent = timing
        ? `${timing.label} · ${timing.phase_label}${timing.phase === "recovery" ? " / 尚不能再出招" : ""}`
        : "自由动作 / 无参考时序";
    for (const [key, value] of Object.entries(frame.recognition.phase)) {
        const element = $(`phase-${key}`);
        element.textContent = phases[value];
        element.classList.toggle("bad", value === "unreliable");
    }
    for (const button of $("events").querySelectorAll("button"))
        button.classList.toggle("current", button.dataset.event === latest?.id);
    for (let i = 0; i < 2; i++) {
        const key = i === 0 ? "one" : "two",
            movement = duel.movement[i];
        $(`health-p${i + 1}`).style.width = `${duel.health[i]}%`;
        $(`guard-p${i + 1}`).style.width = `${duel.guard_energy[i]}%`;
        $(`hp-${key}`).textContent = `${duel.health[i]} HP`;
        const actionPhase = duel.action_phase[i];
        $(`player-${key}-state`).textContent =
            {
                startup: "前摇",
                active: "攻击中",
                recovery: "后摇锁定",
                hitstun: "受击硬直",
            }[actionPhase] || movement.state;
        $(`motion-${key}`).textContent =
            `${movement.state} · ${movement.source_forward_m === null ? "失跟踪" : `${movement.source_forward_m.toFixed(2)} m → ${movement.mapped_forward_m.toFixed(2)} m`}`;
        $(`defense-${key}`).textContent =
            `${duel.defense[i].label} · 防守槽 ${Math.round(duel.guard_energy[i])}`;
    }
    $("duel-distance").textContent = `${duel.distance_m.toFixed(2)} m`;
    $("lane-state").textContent = duel.separation_limited
        ? "近身边界：保持 0.55 m，防止穿过对手"
        : "骨盆位移 → 场景移动 · 距离以角色根节点计";
    const inputCombo = run.events
        .filter((e) => e.combo && e.time_s <= time && time - e.time_s < 2)
        .at(-1);
    $("input-combo").textContent = inputCombo
        ? inputCombo.combo
        : "等待动作序列";
    const result = run.duel.events
        .filter((e) => e.time_s <= time + 0.0001)
        .at(-1);
    const recent = result && time - result.time_s < 1.2;
    $("combat-result").textContent = recent
        ? `P${result.attacker + 1} · ${result.label}`
        : "接近 · 出招 · 观察对手";
    $("combat-combo").textContent =
        recent && result.combo_count > 1
            ? `${result.combo_count} HIT · 连续命中`
            : recent && result.damage
              ? `−${result.damage} HP`
              : "";
    $("combat-banner").dataset.outcome = recent ? result.outcome : "";
    for (const button of $("combat-events").children)
        button.classList.toggle(
            "current",
            button.dataset.result === result?.id,
        );
    const chapter = run.duel.chapters.filter((c) => c.time_s <= time).at(-1);
    $("chapter-detail").textContent = chapter?.detail || run.duel.description;
    for (const button of $("chapters").children)
        button.classList.toggle(
            "active",
            Number(button.dataset.start) === chapter?.time_s,
        );
    $("projection-label").textContent = $("offaxis").checked
        ? "严格眼位 · 需标定"
        : "全身取景 · 保留反应空间";
}
function animate(now) {
    const delta = Math.min((now - last) / 1000, 0.1);
    last = now;
    if (run && !scene.loading) {
        if (playing && $("loading").hidden) {
            time = Math.min(time + delta * +$("speed").value, run.duration);
            if (time >= run.duration) setPlaying(false);
        }
        const [frame, next, alpha, index] = frameAt(time);
        const duel = run.duel.frames[index];
        const nextDuel =
            run.duel.frames[Math.min(index + 1, run.frames.length - 1)];
        const opponent = run.duel.opponent_frames || run.frames;
        const second = opponent[duel.opponent_frame],
            nextSecond = opponent[nextDuel.opponent_frame];
        scene.draw(frame, next, alpha, second, nextSecond, {
            duel,
            nextDuel,
            time,
            index,
            hitboxes: $("hitboxes").checked,
            bones: $("bones").checked,
            wireframe: $("wireframe").checked,
            offaxis: $("offaxis").checked,
            eyeOffset: +$("eye-x").value / 100,
            secondary: $("secondary-motion").checked,
            secondaryMode: $("secondary-mode").value,
            optimized: $("optimized").checked,
            recording: recorder.active,
            playing,
        });
        recorder.frame(
            scene.renderers.map((r) => r.domElement),
            duel,
            time,
        );
        if (recorder.active && time >= run.duration) recorder.stop();
        if (now - lastUi > 60) {
            ui(frame, duel);
            lastUi = now;
        }
        renderCount++;
        if (now - fpsTime > 1000) {
            $("render-fps").textContent =
                `${Math.round((renderCount * 1000) / (now - fpsTime))} FPS`;
            renderCount = 0;
            fpsTime = now;
        }
    }
    requestAnimationFrame(animate);
}

async function start() {
    const arrangeViews = () => {
        document.body.classList.toggle(
            "three-screens",
            $("three-screens").checked,
        );
        const eyes = document.querySelector(".eyes");
        if ($("three-screens").checked)
            document.querySelector(".transport").after(eyes);
        else document.querySelector(".metrics").after(eyes);
        scene?.size();
    };
    $("three-screens").addEventListener("change", arrangeViews);
    document.body.classList.add("showcase");
    $("stage-focus").addEventListener("click", () => {
        const focus = document.body.classList.toggle("showcase");
        $("stage-focus").textContent = focus ? "显示参数" : "专注演示";
        scene?.size();
    });
    arrangeViews();
    $("secondary-mode").addEventListener("change", () =>
        compute({ preserveTime: true }),
    );
    $("benchmark").addEventListener("click", () => {
        if (!run || scene.loading || !$("loading").hidden) return;
        time = 0;
        scene.startBenchmark();
        setPlaying(true);
    });
    try {
        scene = new LabScene();
    } catch (err) {
        $("loading").hidden = true;
        error(`无法初始化 WebGL：${err.message}`);
        return;
    }
    const response = await fetch("/api/catalog");
    if (!response.ok) throw new Error("算法服务没有响应");
    const catalog = await response.json();
    catalog.sources.forEach((source) => {
        const option = document.createElement("option");
        option.value = source.id;
        option.textContent = source.label;
        $("source").append(option);
    });
    $("apply").addEventListener("click", compute);
    $("source").addEventListener("change", compute);
    $("restart-match").addEventListener("click", () => {
        if (!run || scene.loading) return;
        time = 0;
        setPlaying(true);
    });
    $("record-match").addEventListener("click", () => {
        if (recorder.active) {
            recorder.stop();
            return;
        }
        if (!run || scene.loading) return;
        document.querySelector('[data-view="arena"]').click();
        $("speed").value = "1";
        time = 0;
        setPlaying(true);
        try {
            recorder.start(run, (label) => {
                $("record-match").textContent = label;
            });
        } catch (err) {
            error(err.message);
        }
    });
    $("transition-blend").addEventListener("change", () =>
        compute({ preserveTime: true }),
    );
    $("profile").addEventListener("change", compute);
    $("avatar-kind").addEventListener("change", compute);
    $("avatar-asset").addEventListener("change", () => {
        vrmBuffer = $("avatar-asset").value === "local" ? localBuffer : null;
        opponentBuffer = null;
        $("avatar-kind").value = "vrm";
        compute();
    });
    $("import-vrm").addEventListener("click", () => $("vrm-input").click());
    $("vrm-input").addEventListener("change", async () => {
        const file = $("vrm-input").files[0];
        if (!file) return;
        try {
            if (file.size > 40 * 1024 * 1024) throw new Error("VRM 超过 40 MB");
            const candidate = await file.arrayBuffer();
            // Validate and bind before replacing the current playable asset.
            await scene.prepareAvatar(candidate);
            vrmBuffer = candidate;
            localBuffer = candidate;
            opponentBuffer = null;
            let option = $("avatar-asset").querySelector('[value="local"]');
            if (!option) {
                option = document.createElement("option");
                option.value = "local";
                $("avatar-asset").append(option);
            }
            option.textContent = `本地导入 · ${file.name}`;
            $("avatar-asset").value = "local";
            $("avatar-kind").value = "vrm";
            await compute();
        } catch (err) {
            error(err.message);
        }
    });
    $("play").addEventListener("click", () => {
        if (run && time >= run.duration) time = 0;
        setPlaying(!playing);
    });
    $("step").addEventListener("click", () => {
        if (run) {
            setPlaying(false);
            time = Math.min(run.duration, time + 1 / run.fps);
        }
    });
    $("timeline").addEventListener("input", () => {
        if (run) {
            time = (+$("timeline").value / 1000) * run.duration;
            setPlaying(false);
        }
    });
    for (const [id, output, suffix] of [
        ["noise", "noise-value", " mm"],
        ["dropout", "dropout-value", "%"],
        ["cutoff", "cutoff-value", " Hz"],
        ["eye-x", "eye-value", " cm"],
        ["movement-gain", "movement-gain-value", "×"],
        ["initial-gap", "initial-gap-value", " m"],
    ]) {
        $(id).addEventListener("input", () => {
            $(output).textContent = $(id).value + suffix;
        });
    }
    document.querySelectorAll("[data-view]").forEach((button) =>
        button.addEventListener("click", () => {
            const mode = button.dataset.view;
            scene.setMode(mode);
            document
                .querySelectorAll("[data-view]")
                .forEach((b) => b.classList.toggle("active", b === button));
            $("arena-hud").hidden = mode !== "arena";
            $("arena-hud").style.display = mode === "arena" ? "flex" : "none";
            $("combat-banner").hidden = mode !== "arena";
            $("compare-labels").hidden = mode === "arena" || mode === "avatar";
            const labels = $("compare-labels").children;
            labels[0].style.display = mode === "retarget" ? "none" : "";
            labels[1].textContent =
                mode === "retarget" ? "源人体骨架" : "约束骨架";
            $("view-title").textContent = {
                arena: "01 / 位移与空间攻防",
                compare: "02 / 原始 → 约束 → 蒙皮",
                retarget: "03 / 真实动捕骨架 → VRM 全身映射",
                avatar: "04 / 皮套近看 · 拖动旋转 / 滚轮缩放",
            }[mode];
        }),
    );
    $("import-button").addEventListener("click", () => $("file-input").click());
    $("file-input").addEventListener("change", async () => {
        try {
            const file = $("file-input").files[0];
            if (!file) return;
            if (file.size > 20 * 1024 * 1024) throw new Error("文件超过 20 MB");
            const text = (await file.text()).trim();
            uploaded = text.startsWith("[")
                ? JSON.parse(text)
                : text
                      .split(/\r?\n/)
                      .filter(Boolean)
                      .map((line) => JSON.parse(line));
            if (!$("source").querySelector('[value="upload"]')) {
                const option = document.createElement("option");
                option.value = "upload";
                option.textContent = "导入的 PoseFrame";
                $("source").append(option);
            }
            $("source").value = "upload";
            await compute();
        } catch (err) {
            error(`导入失败：${err.message}`);
        }
    });
    $("export-report").addEventListener("click", () => {
        if (!run) return;
        download(
            "dollfight-evaluation.json",
            JSON.stringify(
                {
                    version: run.version,
                    source: run.source,
                    description: run.description,
                    config: run.config,
                    metrics: run.metrics,
                    events: run.events,
                    limitations: run.limitations,
                    combat: {
                        summary: run.duel.summary,
                        events: run.duel.events,
                        description: run.duel.description,
                        limitations: run.duel.limitations,
                    },
                },
                null,
                2,
            ),
        );
    });
    $("export-unity").addEventListener("click", async () => {
        if (!run) return;
        $("export-unity").disabled = true;
        try {
            const response = await fetch("/api/export-unity", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(currentConfig),
            });
            const clip = await response.json();
            if (!response.ok) throw new Error(clip.error);
            download(
                `dollfight-${run.name}-humanoid.json`,
                JSON.stringify(clip),
            );
        } catch (err) {
            error(err.message);
        } finally {
            $("export-unity").disabled = false;
        }
    });
    $("export-pose").addEventListener("click", async () => {
        if (!run) return;
        $("export-pose").disabled = true;
        try {
            const response = await fetch("/api/export", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(currentConfig),
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error);
            download(
                "dollfight-poseframes.jsonl",
                data.frames.map((f) => JSON.stringify(f)).join("\n"),
                "application/x-ndjson",
            );
        } catch (err) {
            error(err.message);
        } finally {
            $("export-pose").disabled = false;
        }
    });
    document.querySelector('[data-view="arena"]').click();
    requestAnimationFrame(animate);
    await compute();
}
start().catch((err) => {
    $("loading").hidden = true;
    error(err.message);
});
