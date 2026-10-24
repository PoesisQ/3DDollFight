// Record the actual three live WebGL canvases, including gameplay HUD. No
// offline rerender, synthetic intermediate frames or prerecorded pose video.
export class MatchRecorder {
    constructor() {
        this.active = false;
    }
    start(run, status) {
        if (!window.MediaRecorder || !HTMLCanvasElement.prototype.captureStream)
            throw new Error(
                "此浏览器不支持录屏，请使用当前版本的 Edge 或 Chrome。",
            );
        this.canvas = document.createElement("canvas");
        this.canvas.width = 1280;
        this.canvas.height = 1000;
        this.context = this.canvas.getContext("2d");
        this.stream = this.canvas.captureStream(30);
        const mimeType = [
            "video/webm;codecs=vp9",
            "video/webm;codecs=vp8",
            "video/webm",
        ].find((t) => MediaRecorder.isTypeSupported(t));
        this.recorder = new MediaRecorder(this.stream, {
            ...(mimeType ? { mimeType } : {}),
            videoBitsPerSecond: 6000000,
        });
        this.chunks = [];
        this.run = run;
        this.status = status;
        this.recorder.ondataavailable = (e) => {
            if (e.data.size) this.chunks.push(e.data);
        };
        this.recorder.onstop = () => {
            this.stream.getTracks().forEach((t) => t.stop());
            const url = URL.createObjectURL(
                new Blob(this.chunks, { type: mimeType }),
            );
            const previous = document.getElementById("last-recording");
            if (previous) {
                URL.revokeObjectURL(previous.href);
                previous.remove();
            }
            const link = document.createElement("a");
            link.id = "last-recording";
            link.href = url;
            link.download = `dollfight-${run.name}-three-rounds.webm`;
            link.textContent = "下载刚才的录像";
            document.getElementById("record-match").after(link);
            link.click();
            status("录制完整演示");
        };
        this.active = true;
        this.recorder.start(1000);
        status("停止录制并下载");
    }
    frame(canvases, duel, time) {
        if (!this.active) return;
        const c = this.context;
        c.fillStyle = "#101b22";
        c.fillRect(0, 0, 1280, 1000);
        const fit = (source, x, y, width, height) => {
            const scale = Math.min(
                width / source.width,
                height / source.height,
            );
            const w = source.width * scale,
                h = source.height * scale;
            c.drawImage(
                source,
                x + (width - w) / 2,
                y + (height - h) / 2,
                w,
                h,
            );
        };
        fit(canvases[0], 0, 58, 1280, 600);
        fit(canvases[1], 0, 700, 636, 300);
        fit(canvases[2], 644, 700, 636, 300);
        c.font = "bold 22px sans-serif";
        c.fillStyle = "#83e2cb";
        c.fillText(
            `DOLLFIGHT   ROUND ${duel.round || 1} / ${this.run.duel.rounds?.length || 1}`,
            24,
            34,
        );
        c.font = "17px sans-serif";
        c.fillStyle = "#eaf1f4";
        c.fillText(
            `${time.toFixed(1)} / ${this.run.duration.toFixed(0)} s   ·   ${duel.intent?.[0] || "真人动捕回放"}`,
            520,
            34,
        );
        c.fillStyle = "#0e191fdd";
        c.fillRect(18, 76, 1244, 53);
        c.fillStyle = "#83e2cb";
        c.fillText(`P1   ${duel.health[0]} HP`, 34, 101);
        c.fillRect(34, 111, duel.health[0] * 4, 6);
        c.fillStyle = "#ee9188";
        c.fillText(`P2   ${duel.health[1]} HP`, 1100, 101);
        c.fillRect(1244 - duel.health[1] * 4, 111, duel.health[1] * 4, 6);
        c.fillStyle = "#eaf1f4";
        c.fillText(`间距 ${duel.distance_m.toFixed(2)} m`, 568, 105);
        c.font = "15px sans-serif";
        c.fillText("玩家一 · 对手全身视角", 24, 686);
        c.fillText("玩家二 · 对手全身视角", 668, 686);
        const event = this.run.duel.events
            .filter((e) => e.time_s <= time)
            .at(-1);
        c.fillStyle = "#0e191fdd";
        c.fillRect(18, 610, 1244, 36);
        c.fillStyle = "#eaf1f4";
        c.fillText(
            event && time - event.time_s < 1.2
                ? `P${event.attacker + 1}  ${event.label}  ${event.damage ? "-" + event.damage + " HP" : ""}`
                : "真人动捕编辑排练 · 非实时相机采集",
            32,
            634,
        );
    }
    stop() {
        if (!this.active) return;
        this.active = false;
        this.recorder.stop();
    }
}
