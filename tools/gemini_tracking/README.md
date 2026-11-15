# Gemini 2 身体 + 手部骨架（替代 Astra 桥）

用一台 Orbbec Gemini 2 直接产出 Unity 已经在读的两种报文：

| 数据 | 端口 | 格式 |
|---|---|---|
| 身体 19 关节 | UDP 7001（同时镜像到 7012） | 与 `AstraUnityBridge` 相同的 `version=1` JSON，单位 mm |
| 手部 21 关节 | UDP 7011 | `dollfight-hands-3` |

**Unity 端不需要改任何代码。** 只要关掉 Astra 桥和 Astra 相机，运行这里的程序，`SingleCameraGame` 接收到的就是它熟悉的格式。

## 运行

```bat
tools\gemini_tracking\run.cmd
```

双击就是完整模式：**会弹出摄像头画面**（带骨架叠加）。命令行等价于：

```bat
tools\hand_tracking\.venv\Scripts\python.exe tools\gemini_tracking\gemini_run.py
```

常用参数：

```text
--no-preview           不打开预览窗口（只跑发送）
--no-skeleton          预览只显示摄像头画面，不画骨架（窗口里按 s 也能切）
--max-poses 1          跟踪人数：1 最快；两人对战用 2，代价约 2 倍耗时
--pose-model full      姿态模型：full 准、lite 快
--pose-every 2         身体每 2 帧算一次；手部每帧都算（手更怕掉帧）
--no-roi               关掉手部 ROI，退回整帧检测（只在排查时用）
--smoothing 10         身体关节平滑率，0 关闭
--no-body / --no-hands 只跑其中一路
--serial <SN>          多台相机时按序列号选
```

快捷键：预览窗口里 `q` 或 `Esc` 退出，`s` 显示/隐藏骨架。

**站位**：相机要能装下你从头顶到腰（最好到膝盖）的整个上半身，距离 **2–2.5 m**。太近时 T 字的手臂会直接出画，MediaPipe 拿不到肩肘，Unity 就会拒绝校准——这不是相机坏了。预览左上角会直接写出当前距离和「请退到 2.5 m 左右」。

## 延迟：为什么之前只有 4 fps

问题不在相机。Gemini 2 本身跑 30 fps，但旧循环把两件事都放在整帧 1280×720 上、每帧各做一次：

| 阶段 | 旧实现 | 现在 |
|---|---|---|
| 身体（full，2 人） | 85 ms | 每 2 帧一次、默认 1 人：摊到每帧约 25 ms |
| 手部（整帧找手） | 36 ms | 每只手一个 320px ROI：约 25–30 ms |
| 预览窗口 | 全尺寸 imshow | 半尺寸 |
| 合计 | 约 230 ms/帧 → 4.3 fps | 离线复测 **31 ms/帧 → 32 fps** |

更要命的是它是个正反馈：帧率越低，两帧之间的动作越大，MediaPipe 越容易跟丢；一跟丢就跑完整检测器（85 ms），帧率再掉。现在手部改成手腕附近的小框跟踪，手在模型输入里占比从 3% 提到 40% 左右，既快又准；离线用你录屏里的 14 帧（握拳状态）复测，**每一帧都能出两只手**，而整帧模式一帧都出不来。

控制台每 2 秒会打印一行 `耗时：采集 xx ms | 身体 xx ms | 手部 xx ms`，换机器或换参数时看这一行就知道瓶颈在哪。

## 预览里的骨架为什么一直闪

不是检测在丢人，是画的时候丢帧。身体每 `--pose-every` 帧才算一次（默认 2），手部每帧都算；旧代码在没有身体解的那一帧画的是空列表，于是骨架以一半帧率在开/关——录屏那台机器 8 fps，就是 4 Hz 的闪。

现在把上一次的解保持 **0.5 秒**（`held_for_preview`）：人还在画面里时每帧都画得上，人走了才消失。代价是骨架最多滞后一个检测间隔，比闪要好看得多。

如果只想看画面不要骨架，启动时加 `--no-skeleton`，或直接在窗口里按 `s` 切。

## 掌心/手背为什么反

**发送端没有反。** 预览会把画面里实际看到的那一面写出来（`hand facing: L:palm R:back`）；它说 `back` 而你正摊着掌心，才说明相机这一层错了。三层依次是：
1. **`HandLift` 的宽高比写死 4:3。** 它用「掌宽 ÷ 掌长」的像素比判断掌心朝向，Astra 是 640×480 所以 4:3 正确；Gemini 是 1280×720，按 4:3 算会让每只手掌看起来窄 25%，正好把「掌心可读 / 不可读」的判断推过阈值，于是一路沿用上一帧的旧朝向——看起来就是掌心手背反过来。现在按实际帧尺寸传入 16:9。
2. **左右手标签会跳。** 一只全帧检测器同时看两只手时，MediaPipe 的 handedness 在握手/侧掌时会来回翻，翻一次就把这只手当成另一只手，掌面自然也跟着翻。现在左右各一个 ROI 跟踪器，框是从对应手腕长出来的，**手的侧别由几何决定，不再问 MediaPipe**。
3. **Unity 侧只把偏航给了手指，没给掌面。** 手的三个轴来自相机坐标系，必须先整体乘上 `liveFacing * sensorToModel`（「人的朝向 → 角色朝向」的偏航）才能喂给角色的手腕。2026-11-13 那版为了「掌面跟人」，把 `z` 留在了相机系，再投影到偏航后的手指平面上——两个坐标系混用。侧身对局里这两套坐标正好差 90°，结果就是手腕被拧了 90°：掌面朝镜头，胳膊和手指却朝着对手。现在三根轴一起转：掌心朝屏幕 = 沿你身体正前方 = 对手的方向，这是「跟着身体」的唯一解，不需要知道偏航是多少。
   - 面板右侧的「掌心 xx°」就是这个角度：**0° = 掌心正对手**，90° = 侧对（拧了四分之一圈），180° = 手背对手。
   - 「翻转：正常 / 已反向」是额外 180°，只在角色的掌背定义和发送端不一致时才需要。

## 它怎么工作

```text
Gemini 2 ── 彩色 1280×720@30 ──┬─ MediaPipe Pose (33 点) ─┐
          └ 深度 1280×800@30 ──┴─ 对齐到彩色 + 内参反投影 ─┴─ 19 关节 (Astra 坐标系, mm) ─ UDP 7001
                                     └─ MediaPipe Hands (21 点) ─ 现有 hand3d 解算 ─ UDP 7011
```

- **深度对齐**：`AlignFilter(COLOR_STREAM)` 把深度搬到彩色像素网格，所以「某个关节点在彩色图上的像素」可以直接读出毫米深度。
- **坐标系**：Astra 的约定是 x = 人物自己的右、y = 向上、z = 背离相机，单位 mm。Gemini 相机系是 x 右、y 下、z 前，所以发送前做 `(-x, -y, z)`。这样 Unity 的 `axisSigns` 和 `MapSensorOffset` 一行都不用动。
- **缺深度的关节**：手借手腕、脚借膝盖、腕借肘、脊柱借髋；只有躯干全丢才整帧丢弃。避免遮挡时骨架塌到相机原点。
- **左右手归属**：用身体的两只手腕在画面里的 x 决定左右，不依赖 MediaPipe 的手性标签（未镜像的相机上它系统性反着）。
- **脊柱四点**：髋部中心、脊柱中部、肩部中点、颈。后三者不是独立测量的：颈必须沿「髋→肩」轴线向上偏移约 20% 躯干长，否则颈和肩部中点会重合，Unity 的校准会直接判「位置过近」并整帧丢弃。
- **关节状态**：Astra 的 `status` 里 `2` 才是 tracked，`1` 是低置信度；发 1 的话面板会显示「低置信度 17」，角色也不会被驱动。
- **人物编号**：按上一帧髋部位置就近匹配，两人交叉时 id 不会互换。
- **手部逻辑**：`tracker` / `hand3d` / `skeleton` / `curls` / `protocol` 全部从 `tools/hand_tracking` 直接 import，只有逐帧循环在这里复刻了一份（含 `HAND_HOLD` 重发与 `HAND_GRACE` 松手）。
- **手部 ROI**：左右各一个 1 手模型。框从身体手腕长出来，每帧向对应手腕回拉 30%，框大小跟着手掌像素跨度自适应；连续 3 帧找不到就丢掉框、0.5 秒后重新再找，避免对着空气跑推理。
- **宽高比**：`HandLift` 的掌宽/掌长比必须按真实帧尺寸算（Gemini 16:9）。写死 4:3 会让掌面朝向判断失效，这是之前掌心/手背反过来的主因。

## 安装依赖

虚拟环境沿用 `tools/hand_tracking/.venv`（Python 3.10，已有 mediapipe / numpy / opencv）。

```bat
uv pip install --python tools\hand_tracking\.venv\Scripts\python.exe pyorbbecsdk2==2.1.3
```

> 注意：PyPI 上 `pyorbbecsdk==1.3.2` 的 `win_amd64` 轮子内容是 macOS 的 `.dylib`／`darwin.so`（发布错误），装上去 `import` 会失败。请用 `pyorbbecsdk2==2.1.3` 的 Windows 轮子；如果 `uv` 仍然解析到 macOS 包，直接下载对应 wheel 解压到 `.venv\Lib\site-packages`。

姿态模型需要单独下载一次（full 9 MB、lite 5.6 MB，都不入库）。`run.cmd` 默认用 full；想用 lite 先下载：

```bat
curl -L -o tools\gemini_tracking\models\pose_landmarker_full.task ^
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task

curl -L -o tools\gemini_tracking\models\pose_landmarker_lite.task ^
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task
```

## 已知限制

1. **这是重建，不是原厂骨架。** Astra SDK 的 19 关节是专用模型；这里是 MediaPipe Pose + 深度反投影，快速动作、遮挡、侧身时抖动更大，`--smoothing` 压得太平又会迟到。
2. **深度精度**：Gemini 2 标称 ≤2% @2m（约 4cm），比 Astra 结构光在 1m 的 ±3mm 粗。关节的 Z 会看到这个噪声，XY 由像素决定，反而更稳。
3. **实测 30 fps 上下**：`--max-poses 1`、身体每 2 帧、手部 ROI 的离线循环是 31 ms/帧；接上相机后还要加采集与对齐，实际看控制台的耗时行。两人对战把 `--max-poses` 改回 2，帧率大约减半。
4. **一个进程独占相机**：先关掉 Orbbec Viewer、Unity 里的「启动摄像头」和 `AstraUnityBridge.exe`。
5. **两人同时**：`--max-poses 2` 可以，但两人重叠时 MediaPipe 会短暂并成一个人；Astra SDK 在这方面更稳。
6. **手的 21 点直接沿用现有链路**，输入从 Astra 彩色换成 Gemini 彩色，协议与阈值没有改。
7. **ROI 依赖身体手腕**：拿不到身体时靠每 0.25 秒一次的整帧检测补框；如果长时间只有手、没有身体，手部会慢一点、偶尔丢。

## 排查

| 现象 | 先看 |
|---|---|
| 没有摄像头画面 | 是不是用了 `--no-preview`；`run.cmd` 默认会开窗 |
| 预览有骨架、Unity 里角色不动 | 预览第二行的「Unity 校准」提示；红字就是 Unity 拒绝的原因 |
| 面板显示「低置信度 N」 | 关节状态码必须是 2；发 1 时面板会全部算低置信度 |
| 面板显示「肩部中点与颈部位置过近」 | 颈和肩部中点必须是两个点，颈部要沿脊柱向上偏移 |
| 深度 0% | 相机是否正对 15cm 以内的物体/镜头被挡；Gemini 有效距离 0.15–10m |
| 找到相机但打不开 | 是否被 Viewer / Unity 面板 / 旧的桥占用 |
| 有骨架但位置偏 | 看预览里骨架是否贴合人；`--smoothing 0` 排除滤波 |
| 手左右反了 | 确认彩色图未镜像；本程序默认 `mirror_sides=True`，与 Astra 一致 |
| Unity 没反应 | 端口 7001/7011 是否被旧进程占用，`AstraSkeletonReceiver` 是否在监听 |
