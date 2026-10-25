// CPU submission cost is not GPU execution time. RAF includes browser scheduling.
const percentile = (values, fraction) => {
    if (!values.length) return 0;
    const sorted = [...values].sort((a, b) => a - b);
    return sorted[Math.floor((sorted.length - 1) * fraction)];
};
export class FrameMeter {
    constructor() {
        this.frames = [];
        this.last = null;
        this.benchmark = null;
    }
    start(meta) {
        this.last = null;
        this.benchmark = { started: performance.now(), meta, frames: [] };
        document.getElementById("benchmark").disabled = true;
        document.getElementById("benchmark").textContent = "正在测量 12 秒…";
    }
    record(frame) {
        const now = performance.now();
        if (this.last !== null) frame.interval = now - this.last;
        this.last = now;
        if (!frame.interval) return;
        this.frames.push(frame);
        if (this.frames.length > 180) this.frames.shift();
        if (this.benchmark) {
            this.benchmark.frames.push(frame);
            if (now - this.benchmark.started >= 12000) {
                const report = {
                    ...this.benchmark.meta,
                    ...this.summary(this.benchmark.frames),
                    measurement:
                        "CPU pose + render submission; RAF interval, not GPU timer or camera-to-display latency",
                    sample_duration_s: (now - this.benchmark.started) / 1000,
                };
                document.getElementById("benchmark-report").textContent =
                    JSON.stringify(report, null, 2);
                document.getElementById("benchmark").disabled = false;
                document.getElementById("benchmark").textContent =
                    "重新测量当前场景 12 秒";
                this.benchmark = null;
            }
        }
        if (!this.lastUi || now - this.lastUi > 500) {
            this.lastUi = now;
            const s = this.summary(this.frames);
            document.getElementById("performance").textContent =
                `${s.fps.toFixed(0)} FPS · RAF P95 ${s.raf_p95_ms.toFixed(1)} ms · 姿态 P95 ${s.pose_p95_ms.toFixed(1)} ms · 提交 P95 ${s.render_submit_p95_ms.toFixed(1)} ms · ${frame.views} 个可见视图 · ${(frame.triangles / 10000).toFixed(1)} 万三角形 / 帧`;
        }
    }
    summary(frames) {
        return {
            samples: frames.length,
            fps:
                (frames.length * 1000) /
                frames.reduce((sum, f) => sum + f.interval, 0),
            raf_p50_ms: percentile(
                frames.map((f) => f.interval),
                0.5,
            ),
            raf_p95_ms: percentile(
                frames.map((f) => f.interval),
                0.95,
            ),
            pose_p95_ms: percentile(
                frames.map((f) => f.pose),
                0.95,
            ),
            render_submit_p95_ms: percentile(
                frames.map((f) => f.render),
                0.95,
            ),
            cloth_p95_ms: percentile(
                frames.map((f) => f.cloth),
                0.95,
            ),
            triangles_per_frame: percentile(
                frames.map((f) => f.triangles),
                0.5,
            ),
            draw_calls_per_frame: percentile(
                frames.map((f) => f.calls),
                0.5,
            ),
            self_body_triangles_p50: percentile(
                frames.map((f) => f.selfTriangles || 0),
                0.5,
            ),
            self_body_culled_meshes_p50: percentile(
                frames.map((f) => f.selfCulled || 0),
                0.5,
            ),
            views: percentile(
                frames.map((f) => f.views),
                0.5,
            ),
            animated_frames_percent:
                (100 * frames.filter((f) => f.animated).length) / frames.length,
            frames_over_33ms_percent:
                (100 * frames.filter((f) => f.interval > 33.4).length) /
                frames.length,
        };
    }
}
