import { LabScene } from "./scene.js";

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
        noise_mm: +$("noise").value,
        dropout: +$("dropout").value / 100,
        cutoff: +$("cutoff").value,
        smoothing: $("smoothing").checked,
        constraints: $("constraints").checked,
        foot_lock: $("foot-lock").checked,
        profile: $("profile").value,
        seed: 42,
    };
    if (value.source === "upload")
        Object.assign(value, {
            frames: uploaded,
            camera_height: +$("camera-height").value,
            camera_distance: +$("camera-distance").value,
        });
    return value;
}
async function compute() {
    const id = ++requestId;
    $("loading").hidden = false;
    $("apply").disabled = true;
    $("error").hidden = true;
    try {
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
        time = 0;
        scene.load(run);
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
        $("description").textContent = run.description;
        const actual = run.source === "cmu_optical_mocap",
            upload = run.source === "uploaded_poseframe";
        $("source-badge").textContent = actual
            ? "真实光学动捕"
            : upload
              ? "外部骨架输入"
              : "合成验证";
        $("source-note").textContent = actual
            ? "CMU 14_01 · 无逐拳类别真值"
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
function ui(frame, secondTime) {
    $("time").textContent =
        `${time.toFixed(2).padStart(5, "0")} / ${run.duration.toFixed(2)}`;
    $("timeline").value = Math.round((time / run.duration) * 1000);
    const latest = run.events.filter((e) => e.time_s <= time).at(-1);
    $("action-label").textContent =
        latest && time - latest.time_s < 0.8 ? latest.label : "待机 / 动作回收";
    const counts = frame.quality.reduce((a, q) => {
        a[q] = (a[q] || 0) + 1;
        return a;
    }, {});
    $("quality-label").textContent =
        `${counts.observed || 0}/19 可靠 · ${counts.predicted || 0} 预测 · ${counts.missing || 0} 缺失`;
    $("state-label").textContent = frame.recognition.state;
    for (const [key, value] of Object.entries(frame.recognition.phase)) {
        const element = $(`phase-${key}`);
        element.textContent = phases[value];
        element.classList.toggle("bad", value === "unreliable");
    }
    for (const button of $("events").querySelectorAll("button"))
        button.classList.toggle("current", button.dataset.event === latest?.id);
    const attacks1 = run.events.filter(
        (e) =>
            e.time_s < time &&
            !e.action.startsWith("dodge") &&
            e.action !== "crouch",
    ).length;
    const attacks2 = run.events.filter(
        (e) =>
            e.time_s < secondTime &&
            !e.action.startsWith("dodge") &&
            e.action !== "crouch",
    ).length;
    $("health-p2").style.width = `${100 - attacks1 * 5}%`;
    $("health-p1").style.width = `${100 - attacks2 * 5}%`;
    $("projection-label").textContent = $("offaxis").checked
        ? "窗口透视"
        : "普通 LookAt";
}
function animate(now) {
    const delta = Math.min((now - last) / 1000, 0.1);
    last = now;
    if (run) {
        if (playing && $("loading").hidden)
            time = (time + delta * +$("speed").value) % run.duration;
        const [frame, next, alpha] = frameAt(time);
        const secondTime = (time + 4.5) % run.duration;
        const [second, nextSecond] = frameAt(secondTime);
        scene.draw(frame, next, alpha, second, nextSecond, {
            bones: $("bones").checked,
            wireframe: $("wireframe").checked,
            offaxis: $("offaxis").checked,
            eyeOffset: +$("eye-x").value / 100,
        });
        if (now - lastUi > 60) {
            ui(frame, secondTime);
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
    $("profile").addEventListener("change", compute);
    $("play").addEventListener("click", () => setPlaying(!playing));
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
            $("compare-labels").hidden = mode === "arena";
            const labels = $("compare-labels").children;
            labels[0].style.display = mode === "retarget" ? "none" : "";
            labels[1].textContent =
                mode === "retarget" ? "源人体骨架" : "约束骨架";
            $("view-title").textContent = {
                arena: "01 / 极简对战场景",
                compare: "02 / 原始 → 约束 → 蒙皮",
                retarget: "03 / 相同动作 · 不同身体比例",
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
                },
                null,
                2,
            ),
        );
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
    requestAnimationFrame(animate);
    await compute();
}
start().catch((err) => {
    $("loading").hidden = true;
    error(err.message);
});
