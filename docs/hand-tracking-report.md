# 手部追踪交付说明

> 本文分三部分：**Ⅰ 现状**（做了什么、量到什么）、**Ⅱ 使用说明**（怎么装、怎么跑、出问题看哪里）、**Ⅲ 开发日志**（按日期记录症状 → 原因 → 改动 → 验证）。
> 算法推导、协议字段、章节化设计见[手部识别技术大纲](hand-tracking.md)；模块内的命令与报文细节见 [tools/hand_tracking/README.md](../tools/hand_tracking/README.md)。

---

# Ⅰ 现状

## 1.1 一句话

Astra 的彩色画面 → MediaPipe 21 点 → 掌面姿态与手指弯曲 → UDP 报文 → 角色手骨逐指节驱动。**四个可玩角色都能被驱动**，手指能张开、能握拳、能单指动作，手腕能跟着翻掌与压腕。

## 1.2 链路

```
Astra 彩色 640×480 (TCP 7005, DFCF 头 + RGB24)
        │
        ├── MediaPipe HandLandmarker ── 21 点 (2D) + 21 点 (world) + 左右手
        │
        ▼
hand3d.HandLift.solve(2D, side, basis=world)          tracker.image_frame(world)
   ├ 掌面三轴：直接取 world landmarks 的正交化结果
   ├ 每根手指：拟合弯曲量 → 按真人屈曲曲线展开三段指骨
   └ 21 个关节在手自身坐标系里
        │
        ▼
protocol dollfight-hands-3 (UDP 7011, JSON)
        │
        ▼
AstraHandReceiver → AstraLivePlayer.ApplyHands
        │
        ▼
HumanoidReplay.ApplyHandSkeleton
   ├ 手腕：把角色手腕的框架对齐到实测 basis（三自由度）
   └ 每根指骨：沿实测段方向旋转
```

## 1.3 实现了什么

| 能力 | 落在哪里 | 状态 |
|---|---|---|
| 手部检测（双手、21 点、置信度） | `tools/hand_tracking/tracker.py` | 可用 |
| 掌面姿态（翻掌 / 压腕 / 侧对） | `run.py::palm_frame` → `hand3d.solve(basis=)` | 可用，取 MediaPipe world landmarks |
| 手指弯曲（逐指、含拇指） | `hand3d._fit_curl` | 可用 |
| 单指动作（只伸食指等） | 同上，逐指独立 | 可用 |
| 21 点低通（静止不抖、握拳不拖） | `hand3d._settle` | 可用 |
| 左右手配对（不依赖镜像假设） | `run.py::assign_sides` + UDP 7012 | 可用，缺身体数据时回退标签 |
| 手骨驱动（腕三自由度 + 逐指段方向） | `HumanoidReplay.ApplyHandSkeleton` | 可用，不再等身体校准 |
| 没有身体校准时仍然驱动手指 | `AstraLivePlayer.LateUpdate` → `ApplyHands` | 可用，本轮解耦 |
| 断流后手势回位 | `HumanoidReplay.RelaxHand`，1 秒宽限 | 可用 |
| 旧版仅弯曲度兼容 | `HumanoidReplay.ApplyFingerCurls` | 保留 |
| 四角色手骨齐全性审计 | `tools/audit_hand_rigs.py` + `tests/test_hand_rigs.py` | 可用，四角色各 15/15/手 |

## 1.4 关键文件

| 文件 | 作用 |
|---|---|
| `tools/hand_tracking/run.py` | 主循环：收帧、推理、求解、发报文、预览 |
| `tools/hand_tracking/hand3d.py` | 二维 → 三维手：掌面、弯曲量拟合、指骨展开 |
| `tools/hand_tracking/tracker.py` | MediaPipe 封装与坐标约定 |
| `tools/hand_tracking/skeleton.py` | 关节索引、掌面正交基、合理性判据 |
| `tools/hand_tracking/curls.py` | 兼容路径的 15 个弯曲度与分类 |
| `tools/hand_tracking/protocol.py` | `dollfight-hands-3` 编解码 |
| `unity/Assets/AstraUnity/Runtime/AstraHandReceiver.cs` | UDP 7011 接收与校验 |
| `unity/Assets/AstraUnity/Runtime/HandFrame.cs` | 报文结构 |
| `unity/Packages/com.dollfight.humanoid/Runtime/HumanoidReplay.cs` | 手骨绑定与驱动 |
| `tools/audit_hand_rigs.py` | 四角色手骨审计（不依赖 Unity） |
| `docs/hand-tracking.md` | 技术大纲与逐轮失效分析 |

## 1.5 量到的数字

| 指标 | 数值 | 来源 |
|---|---:|---|
| 四角色每只手可动指骨 | 15（拇指 3 + 四指各 3） | `tools/audit_hand_rigs.py` |
| 运行时绑定手骨 / 弯骨 | `handBones=30` `curlBones=30` | `unity/Library/AstraLiveStatus.txt` |
| 掌面法线与实测夹角（旧 → 新） | 中位 63.9° → 0°；p90 132° → 0° | 50 秒录屏逐帧 |
| 弯曲量对独立参照的平均误差（旧 → 新） | 0.240 → 0.146 | 同上 |
| 前倾 63° 时手掌重建尺度（旧 → 新） | ×2.2 → ×1.0 | 合成手 |
| 静止手 21 点帧间抖动（滤波前 → 后） | 0.0445 → 0.0223 掌长 | 合成手 1.6 px 噪声 |
| **握拳累积弯曲（修前 → 修后）** | **114.4° → 255°**（60 fps） | `ApplyHandSkeleton` 等价模拟 |
| **腕部 90° 目标实到（修前 → 修后）** | **23.3° → 90°** | 同上 |
| 修后收敛时间 | 约 4 帧 / 67 ms | 同上 |
| 手部模块测试 | 55 passed / 1 skipped | `uv run pytest -q tools/hand_tracking/tests` |
| 全仓库测试 | 230 passed / 9 skipped | `uv run pytest -q` |

## 1.6 已知限制

| 限制 | 原因 | 影响 |
|---|---|---|
| 掌心/手背二义性 | 单目观测固有；一个视角无法区分「朝我」与「背我」 | 手**首次出现就侧对镜头**时可能镜像一两帧 |
| 手指直指镜头 | 投影只剩几个像素 | 该帧沿用上一帧弯曲量，不猜 |
| 手小于约 60 px | MediaPipe 检出率下降 | 退到 1.5 m 内、开灯 |
| 结构光深度未接入 | 桥目前只推彩色；深度对 12–18 mm 的手指本身也不可靠 | 掌面靠 world landmarks，不靠深度 |
| 双人同时入镜 | 只取置信度最高的两只手 | 单人使用 |
| Unity 侧编译 | 编辑器占着工程时无法 batchmode | 改动需在编辑器里自动重编译后确认 |

---

# Ⅱ 使用说明

## 2.1 前置条件

- Windows 10/11，Astra 相机（Orbbec SDK 驱动已装）
- Unity **6000.3.27f1**（Hub 打开 `unity/`）
- Python 3.10（由 `uv` 创建，不需要系统 Python）
- 桥接程序已构建：`integrations/astra-unity-bridge` 下 `Build-Bridge.cmd`，产物在 `build/bin/Release/AstraUnityBridge.exe`

## 2.2 装一次

```bat
cd tools\hand_tracking
install.cmd        :: 建 .venv（Python 3.10）并装 MediaPipe
fetch_model.cmd    :: 下载 hand_landmarker.task（约 7.8 MB）
```

模型不随仓库分发；`.venv/` 与 `models/` 已被 Git 忽略。装完可自检：

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 2.3 每次运行

**顺序不能颠倒**——一台 Astra 同时只能被一个进程占用。

1. Unity 打开 `Assets/AstraUnity/SingleCameraGame.unity`，Play，完成选角。
2. 在 Unity 面板上**停止「启动摄像头」**（它和 `run.cmd` 抢同一台相机）。
3. 双击 `tools\hand_tracking\run.cmd`。
   等价于 `python run.py --start-bridge --preview`，会自己拉起桥接程序。
4. 站到 1.5 m 左右，让**双手完整入画**，正对镜头停 1 秒。
5. 关掉命令行窗口即停止。

端口分配：

| 端口 | 协议 | 用途 |
|---|---|---|
| 7005 | TCP | 彩色帧（桥 → Python） |
| 7011 | UDP | 手部骨架（Python → Unity，`AstraHandReceiver.port` 默认值） |
| 7012 | UDP | 身体骨架镜像（桥 → Python），只用于左右手配对；`--body-port 0` 可关 |

## 2.4 站位与手势

- **距离**：1.0–1.5 m 最稳；2.0 m 时手掌只剩约 75 px，弯指开始飘。
- **光线**：Astra 彩色偏暗（中心像素实测 40–80），背光会显著掉点。
- **入画**：双手都在画面内，手腕不要贴边。
- **校准**：不需要专门动作。掌面姿态每帧直接从 world landmarks 取，没有「等它学」的过程；1 秒宽限只用于手被短暂遮挡。
- **格斗常态握拳**：可以一直握着，不必先张开让系统「看到」——这是本版相对上一版的区别。

## 2.5 怎么确认它在工作

看 `unity/Library/AstraLiveStatus.txt`，每秒刷新一次：

```
time=2026-11-10 13:20:41
scene=DollFight
body.listening=True receiving=True frames=14512 error=-
hand.listening=True receiving=True frames=4355
game=True ready=True selectionOpen=False actor=True calibrated=False
hands.ready=True driving=True handBones=30 curlBones=30 rollL=12 rollR=0 handFrames=4355 legNote=左膝、右膝
status=Waiting for automatic T-pose calibration
```

| 字段 | 含义 | 不正常时说明 |
|---|---|---|
| `hand.listening` | UDP 7011 是否绑定 | False：端口被占，点面板「重连」或彻底退出 Unity |
| `hand.receiving` | 0.6 s 内是否收到报文 | False 但 listening True：`run.cmd` 没在发 |
| `hand.frames` | 累计接受帧数 | 不增长：报文被校验拒了 |
| `hands.ready` | 角色手上是否绑到指骨 | False：Console 找 `No finger bones resolved` |
| `hands.driving` | 这一帧是否真的把手指写进了角色 | False 但 `receiving=True`：报文里没有可用骨架，或选角界面还开着 |
| `handBones` / `curlBones` | 绑定到的指骨数 | 正常 30/30 |
| `rollL` / `rollR` | 手腕相对绑定姿势的转角（度） | 翻掌时应有明显变化；恒为 0 说明 basis 没到 |
| `aimL` / `aimR` | 指骨离目标方向还差多少度（均值） | 应接近 0。持续偏大 = 有别人在写同一批骨头 |
| `bendL` / `bendR` | 中指指尖相对掌面的弯角（0 直、90 折回掌心） | 张开手时应接近 0；它不动而 `aim` 在涨，就是手指没被驱动 |
| `frameYaw` | 传感器朝向与角色朝向的偏航差（度） | 手部基向量必须先转这个角再交给手腕。单人正面站位约 180，侧面对战约 ±90 |
| `calibrated` | 身体是否完成标定 | **只影响身体**；False 时手指照常驱动 |
| `legNote` | 缺的关节名 | 如「左膝、右膝」= 腿部没入画 |

## 2.6 排查表

按「症状 → 先看什么 → 通常原因」的顺序，比猜快。

| 症状 | 先看 | 通常原因与处理 |
|---|---|---|
| 面板一直「未收到手部数据」 | `hand.listening` | 端口冲突，点面板「重连」；仍失败彻底退出 Unity |
| `hand.receiving=False` | 命令行有没有在出帧 | `run.cmd` 没启动，或彩色流断开 |
| **整个角色都不动，面板写「自动校准失败」** | 控制行 + `calibrated` | 身体需要 T 字校准；**手指不受影响**，现在没校准也会动。若连手指都不动，先看 `hands.driving` |
| 角色手指完全不动 | `hands.ready` / `hands.driving` / Console | `no finger bones`：角色没有指骨，或 Avatar 没映射（已按名字回退，含 `Pinky→Little`、`*End` 跳过）；`driving=False` 而 receiving=True：报文里没有骨架（Python 侧 `solve` 返回 None，多半是手掌侧对镜头） |
| 校准好了过一会儿又变成「失败」 | 控制行 | 历史原因：单帧丢人就把校准清掉、且每 5 秒复检的失败文案会盖掉「已校准」。现已加 2 秒宽限，已校准就不再报失败 |
| 握拳只握到一半 / 手指像爪子 | 手感 + `rollL/rollR` | 已修：Unity 侧每帧重置导致只走到目标的 26%。若仍如此，确认 `HumanoidReplay.cs` 是最新版本并已重编译 |
| **手一直是握拳、只跟着动一点点、还在抖** | `aimL/aimR` + `bendL/bendR` | 2026-11-11 修：回放每帧先把 19 根骨头（含两只手腕）写回片段姿势，手部再往上叠 13%（130 fps 下的 `handSmoothing`），于是屏幕上是「87% 回放 + 13% 追踪」——一个几乎不动的半握拳。现在实时驱动期间回放不再写手腕与指骨，`bend` 应随张开/握拳大幅变化 |
| 手腕朝向翻 180° | `rollL/rollR` | 历史原因：`wire_axes` 少做 `(x,-y,-z)`，腕子恒定差 180°。现已固定 |
| 手拿在胸前就乱 | 手掌在画面里的大小 | 历史原因：掌面靠推断 + 投影矩阵尺度错（放大 1/cos 前倾）。现已改为实测 basis |
| 手掌朝上/朝下但角色掌心朝反 | — | 点面板「手掌：正常 / 已反向」，等价于 `AstraLivePlayer.flipPalmNormal` |
| 左右手反了 | `--mirror` | 有身体数据时由手腕左右顺序决定；否则用 `--no-mirror` 关闭交换 |
| 手掌很小、识别不到 | — | 靠近到 1.5 m 内、开灯 |
| 拇指一直伸着 / 握拳时拇指不贴掌 | — | 历史原因：拇指的弯曲方向按掌面法线建，真人其实是贴着掌面横着收。已改为横向朝掌心收；但 MediaPipe 对收起的拇指只给一条近直线，读不出弯曲时仍按上一帧保持 |
| 张开和握拳看起来一样 | 手部骨架（掌心平面）小窗 | 若小窗里手指是**摊开的扇子** → 弯曲量没上去（Python 侧）；若是**折回掌心的短链** → Python 对、Unity 没跟上（C# 侧） |

最后一行是这一轮最重要的分诊方法：**小窗是 Python 侧的真相，角色是整条链路的真相**，两者不一致就说明问题在 Unity。

## 2.7 性能与关闭

- 单帧开销主要在 MediaPipe 推理（CPU），实际帧率看 `--preview` 窗口左上角的 `fps`；低于 15 手感会明显发顿，先确认没有别的程序占着相机。
- 发送频率与帧率相同，每帧一包；画面里没有手时每 0.2 s 发一包空报文保持心跳。
- Unity 侧 `timeoutSeconds=0.6`，超过即视为断流并 `RelaxHand`。
- 关闭：先关命令行窗口（会 terminate 它拉起的桥），再退出 Unity Play。反过来会让桥留在后台占相机。

---

# Ⅲ 开发日志

只记「症状 → 量到的原因 → 改动 → 验证」，不记过程。失败的分析也保留，因为同一个坑会回来。

## 2026-11-09 ｜ 立项与第一版

**症状**：19 点身体契约里没有手指，角色手是固定先验握拳。

**做法**：
1. 核查摄像头能力：Astra 的 `hand_capi` 只给掌心点，深度流只有距离 → 手指只能用彩色 + 关键点。
2. 第一版直接取 MediaPipe 的 `world_landmarks`。录屏实测它在手背离镜头时塌（掌长 100→36 mm、掌宽 65→7 mm、帧间掌法线最大转 120°），且分不出弯没弯：同一段录屏按人眼分组，张开手 144.8°、握拳 134.6°，**方向是反的**。
3. 改为二维重建：手掌当刚性平面定姿态，手指当一自由度链，用「弦长比 + 二维折返度」反解弯曲量，再按真人屈曲曲线摊到三个关节。
4. Unity 侧新增 `ApplyHandSkeleton`：腕三自由度 + 每根指骨沿实测段方向旋转；角色 Avatar 无手指槽，改为按骨骼名回退（`Pinky→Little`、跳过 `*End`）。

**验证**：手部 36 项单测；角色手骨 30/30 绑定；单指动作可用。

## 2026-11-10 上午 ｜ 抖动与手骨审计

**症状**：「效果还是很差」；同时要求「要么四个角色都加手骨，要么都不加」。

**量到的原因**：
1. 21 个关节点从未滤波（只有弯曲量滤了）。手在画面里 60–90 px 时，点噪声让手指缓慢爬行。
2. 手骨是否存在没人量过，只凭肉眼。

**改动**：
1. `hand3d._settle`：带门限的一阶低通，`POINT_SMOOTHING=0.65`、`POINT_SNAP=0.20` 掌长——超过门限判为真实运动，原样放行。抖动 0.0445 → 0.0223 掌长，握拳仍在 2 帧内闭合。
2. `tools/audit_hand_rigs.py`：从文件层面解析 prefab 的 `m_Name` 与 VRM 的 `VRMC_vrm.humanoid.humanBones`，按与 `HumanoidReplay` 相同的名字归一化规则统计。

**验证**：四角色各 15/15/手，无需补骨架；`tests/test_hand_rigs.py` 钉住 4×2×15。

## 2026-11-10 中午 ｜ 弯曲量重写

**症状**：「只要手不是完全正对镜头，就分不出张开还是握拳；手拿到胸前骨架就乱」。

**量到的原因**（把录屏的摄像头小窗逐帧喂回管线）：
1. 旧判据是「指根→指尖弦长 ÷ 手掌投影长度」。掌长是全手最不稳定的数：t=24 那帧只剩 22.7 px（前一秒 60 px），弦长比冲到 **2.35**（伸直的手指最多 0.88），被 `CHORD_CEILING=1.30` 钳住 → 读数恒 0.00，**拳头读成张手**。握拳恰好是掌长投影最短的姿势，也就是最容易饱和的那一档。
2. 掌长轴一律假设在像平面内。前倾 >25° 时假设失效，投影模型整条错。

**改动**：
1. `_fit_curl`：按候选弯曲量重建手指并投影，与观测到的三段指骨比对，只差一个整体缩放（最小二乘）。自由缩放让「整体被压扁」从答案里消失，不再有可饱和的比值。
2. `_frame`：用「观测宽长比 ÷ 标定宽长比」把前倾与 roll 分开。
3. 求逆从「除以法线深度」改为 2×2 矩阵求逆（那个除法在侧对镜头时发散）。
4. `run.py`：手部状态清理从「立刻」改为 1 秒宽限 `HAND_GRACE`。

**验证**：同一条录屏，握拳段 0.00/0.18/0.71 → 0.84–1.00；张手段 0.00–0.30。

## 2026-11-10 傍晚 ｜ 掌面改用实测，修尺度错

**症状**：「能不能不用 2D 投影，Astra 不是 3D 摄像头吗；以前用 MediaPipe 做开源项目没这么差」。

**量到的原因**：
1. 掌面是**推断**的，与 world landmarks 给出的实测相比，中位差 **63.9°**、p90 132°、最大 173°——不是「有点误差」，是方向随时可能反过来。推断靠「掌宽/掌长比」，基准是本次会话见过的最宽；手一直举着就永远猜不准。
2. 二维关键点按**投影后**掌长归一化，而 2×2 投影矩阵用单位轴，差一个 `cos(前倾)`：前倾 63° 时指根被放大 **2.2 倍**，指骨却还是原长。
3. `tracker.upright` 把 world landmarks 翻成 Y 朝上，而下游全按 Y 朝下写，差一个绕 x 的 180°。

**改动**：`tracker.image_frame`（统一到图像系）、`run.py::palm_frame`（取正交化三轴）、`hand3d.solve(basis=)`（给了就用，退化回退推断）、投影矩阵先除 `cos(前倾)` 再求逆。

**关于 Astra 的深度**：桥只推彩色（`native/main.cpp --color-port` 发 `DFCF` + RGB24），`feed.py` 也只认这一种包，链路里没有深度流、没有深度端口、没有彩色↔深度配准。深度唯一能顶替的正是「掌面朝向」，而那恰好是 world landmarks 免费给出的量；对手指这种 12–18 mm 的细圆柱，结构光会丢斑。所以这一轮不接深度。

**验证**：掌面夹角 63.9°/132° → 0；弯曲量误差 0.240 → 0.146；前倾 63° 尺度 ×2.2 → ×1.0；合成手前倾 63° 指尖误差 0.64 掌长 → 0.00。

## 2026-11-10 晚 ｜ 修 Unity 侧欠旋转（本轮）

**症状**：「手指握拳等的东西还是不太行」。

**量到的原因**：这次不在 Python 侧，而在 `HumanoidReplay.ApplyHandSkeleton` 的平滑写法。

```csharp
// 修改前
hand.localRotation = handLocalBinds[side];              // 每帧先重置到绑定姿势
for (...) bones[i].localRotation = handBindRotations[side][i];
for (...) bone.rotation = Quaternion.Slerp(bone.rotation,
              Quaternion.FromToRotation(current, desired) * bone.rotation, t);
```

每帧先把所有骨骼**重置回绑定姿势**，再朝目标插值 `t`（`t = 1 - exp(-18 · dt)`，60 fps 下 0.259）。重置把上一帧的进度全部抹掉，于是插值永远积累不起来，姿势停在一个**固定分数**的目标上，而不是收敛到目标：

| | 目标 | 修前（60 fps） | 修前（90 fps） | 修后 |
|---|---:|---:|---:|---:|
| 握拳三段累积弯曲 | 255° | **114.4°** | **84.5°** | 255° |
| 腕部转角 | 90° | **23.3°** | — | 90° |

114° 的指尖是什么样：手指弯了，但没有绕回掌心——看起来是**一把松开的爪子**，而不是拳。腕部同时只转到目标的四分之一，等于掌心朝向也没跟上。帧率越高越糟。

**改动**（`unity/Packages/com.dollfight.humanoid/Runtime/HumanoidReplay.cs`）：
1. 删掉每帧的绑定姿势重置（腕一处、指骨一处）。位移式瞄准本来就是安全的：`handBindDirections` 是**骨骼自身空间**里的方向，`bone.rotation * direction` 无论骨骼怎么转都等于它的真实段方向，所以 `FromToRotation` 只需要补剩余的差。
2. 保留 `Slerp`，但它现在是一阶滤波：从当前位置收敛到目标，60 fps 约 4 帧（67 ms）。
3. 补两处：`t` 加 `Clamp01`（暂停恢复时 `dt` 可能很大）；残余夹角小于 0.15° 时跳过，避免噪声驱动的微抖。

**验证**：把这段循环按 C# 的语义（含父子继承）逐帧模拟，得到上表。**Unity 侧本轮没能在 CI 里编译**——编辑器开着工程，batchmode 起不来，所以这一条需要在编辑器里自动重编译后由人确认；Python 侧未改动。

## 2026-11-10 晚 ｜ 文档整理

新增本文；`docs/hand-tracking.md` 补 11.4 节记录欠旋转；模块 README 的排查表补「握拳只握到一半」一行。

## 2026-11-10 下午 ｜ 手部一直在跑，但一次都没上屏

**症状**：一段 74 秒的录屏里，面板从头到尾写着「手部：已接入 2 只手（21 点骨架 + 腕部旋转，30 根指骨）」，角色却完全不动；控制行从第 10 秒起恒为「自动校准失败：请面向摄像头双臂平举」。

**量到的原因**（读代码 + 把录屏面板逐秒裁出来对照，不猜）：

1. **手部是身体校准的下游。** `AstraLivePlayer.LateUpdate` 第一行是 `if (!Calibrated || …) return;`，而 `ApplyHands()` 在它后面。身体没做 T 字，`Calibrated` 永远是 false，手部链路再准也走不到写骨骼那一步。这一条把前面几轮的所有改进全部挡在了屏幕外。
2. **校准极脆。** `bodies.Length == 0` 一帧就把 `Calibrated` 清零，恢复却要重新摆一次 T 字；而 `Update` 每 5 秒复检，失败文案会盖掉已经成立的「已校准」。10:34 那段录屏第 5 秒已校准、第 20 秒又变回「失败」，就是这个组合。

**改动**：

1. `LateUpdate` 拆成 `ApplyBodyPose(body)` 与 `ApplyHands()`：**身体姿态要校准，手部不要**。没校准时手指照样跟着摄像头动，手腕沿用角色当前姿势；校准时两者按顺序叠加。
2. 人体丢失给 2 秒宽限（`BodyGrace`），不再一帧清零，短暂遮挡不用重摆 T 字。
3. 只有「未校准」或「真的又摆出了 T 字」才跑校准检查；已校准时不再被失败文案覆盖。
4. 新增 `handsDriving` / 状态文件 `hands.driving`：区分「报文到了」与「真的写进角色了」。没有手部数据时不再把角色自己的手部姿势掰回绑定姿势。
5. 面板与操作提示写清楚「手指不需要校准」。

**拇指**（`hand3d._thumb_bend`）：原来拇指沿**掌面法线**弯曲——那是四根手指的方向。四指绕指关节离开掌面，拇指却是**贴着掌面横着收**（握拳时压在食指上）。方向错了，任何候选弯曲量都复现不出相机看到的折叠链，拟合只好一直回答「伸直」：录屏里拇指全程 0.00，包括明显收起的帧。改成沿掌面横向、略微抬离表面后，同样的弯曲量下指尖从「出掌 0.53 掌长」变成「横跨 0.49、离面 0.17」。

需要说清楚的限制：**这一条不能凭空变出信息**。实测那几帧 MediaPipe 把收起的拇指报成一条接近直线的长链（弦长 1.4 掌长，拇指全长只有 0.78），2D 上确实没有弯曲可读，拟合仍会保持上一帧。改的是「有信号时弯的方向对不对」，不是「没信号也能猜」。

**验证**：
1. 新增 `tools/check_unity_scripts.py`：用 .NET SDK 引用编辑器自带引擎程序集做离线类型检查。此前每次都说「编辑器开着工程，编译不了」，现在两秒出结果，能报到文件与行号（故意写错一行验证过，能抓到）。
2. 手部 56 passed / 1 skipped；全仓库 230 passed / 9 skipped；ruff 全过。
3. 拇指几何有单测钉住：闭合的拇指必须横跨掌心（>0.35 掌长）且离掌面不超过 0.25 掌长。

## 2026-11-11 上午 ｜ 手一直是半握拳，而且抖

**症状**（用户原话）：常态就是握拳；手在变，皮套不跟；手掌张开时角色仍是握拳并抽搐；只伸一根或几根手指完全没变化。而「手部骨架（掌心平面）」小窗里的动作很明显。

**先排除了 Python 侧**。把 11-11 那段 44 秒录屏按摄像头画面的位置回放一遍真管线：

```
 8.0s Right   In z0=+0.00 平面=0.42 尖=(-0.51,+1.84,+0.00)
             Mi z0=+0.00 平面=0.46 尖=(-0.04,+1.95,+0.00)
             curls: {'Thumb': 0.0, 'Index': 0.0, 'Middle': 0.0, 'Ring': 0.0, 'Little': 0.0}
```

每个指尖 `z` 都是 0、`y` 在 1.8–1.95 掌长，五根手指的 curl 全 0，确实是一只摊开的手。所以发出去的 21 点是对的，问题在映射。

**量到的两个原因**：

1. **两个写入者，胜者每帧把另一个抹掉。** `DollFightDemo.LateUpdate`（执行顺序 12000）每帧调 `Actors[i].Apply(time)`，它把 19 根身体骨**连同 7、10 两根手腕**写回回放姿势，并对 15 根指骨写死 `(0.08 + handClose) * fingerAngles`——一个固定的半握拳。`AstraLivePlayer`（12500）随后才把手部叠上去，但那里是**一阶滤波**：`t = 1 - exp(-handSmoothing * dt)`，`handSmoothing = 18`。录屏里游戏视图跑 130 fps，`dt = 7.7 ms`，于是 `t = 0.129`。回放先把手腕/手指写死，手部再推 13%，下一帧回放又抹回去——屏幕上稳定停在「87% 回放 + 13% 追踪」。这解释了全部三个现象：一直半握拳、张开只动一点点、伸一根手指看不出来。它不是「顺序错了」，顺序本来就是对的（12000 < 12500）；错的是**每帧重置 + 一阶滤波**这个组合，26% 那个老问题换了一层又出现了一次。
2. **手腕的朝向来自最不稳定的那个量。** 手腕的世界旋转是 `LookRotation(humanZ, humanY)`，`humanZ`/`humanY` 来自 MediaPipe 的 world landmarks。把这段录屏的基向量逐帧量一遍：中位 3.7°、p90 11.8°、**最差 167.4°**——掌面法线偶尔翻到手背那一侧，下一帧又翻回来。Unity 每帧朝它走 13%，于是手在 180° 之间来回甩，就是抽搐。

**改动**：

1. `HumanoidReplay`：新增 `handPoseOverridden` / `wristOverridden`。实时驱动期间 `Apply` 不再写 15 根指骨，也不再写 7/10 两根手腕（`liveRotations` 仍然更新，松手时不会跳）。AstraLivePlayer 只在**真的有实测 basis**时才接管手腕——没有 basis 时手臂仍归回放，手才不会从胳膊上掉下来。
2. `AstraLivePlayer.ApplyBodyPose`：同上，`wristOverridden` 时不写 7/10。
3. `hand3d._settle_basis`：给实测的手掌基向量加连续性门控。超过 `BASIS_MAX_STEP = 35°` 的帧判为分支翻转、沿用上一帧；`10°` 以内是噪声、做 0.5 的平滑；两者之间原样通过（真转头不给延迟）。同一段录屏复测：`z` 最大跳变 **167.4° → 33.9°**，p90 **11.8° → 9.7°**。因为 21 点是用被接受的那一帧投出来的，点和基向量始终属于同一个坐标系。**这条门控后来被证明会锁死手（见下文（三）），`BASIS_MAX_STEP` 已删除**；抖动改由「2D 判号 + `BASIS_SNAP` 平滑」处理，效果更好且没有状态。
4. `HumanoidReplay.ApplyHandSkeleton`：手腕加 `wristTurnRate = 720°/s` 上限，一帧坏基向量最多掰 12°，而不是整只手翻过去。
5. `BindHandSkeletons`：`count == 1`（整根手指只有一节骨）时，方向原本取 `hand.position - bone.position`——指向手腕，正好反 180°。这一根手指会被每帧推离目标，折回掌心卡住。改成掌面正向 `along`。
6. 诊断：状态文件新增 `aimL/aimR`（指骨离目标还差多少度）、`bendL/bendR`（中指指尖相对掌面的弯角）。面板手部行直接显示「中指屈 L/R」。这两个数能把「手指在跟」和「有别人按着这只手」分开。

**验证**：手部 25 passed（新增 2 条：翻转的基向量不许甩手腕、25°/帧的真翻掌不许被滤波拖住）；全仓库 230 passed / 9 skipped；ruff 全过；离线 Unity 编译 0 错误。

## 2026-11-11 上午（二）｜手掌朝向差 90°：手部基向量没进角色坐标系

**症状**（用户原话）：手指终于正常了，但手掌是面向屏幕正前方的；真手掌平行于身体时，皮套的手掌却垂直于角色。怀疑多转了 90°。

**查证**：不是多转了一个写死的 90°，是**少转了一个不固定的偏航角**，只是这一局恰好是 90°。

- 身体每根骨头都由 `Direction()` 给出方向，而 `Direction()` 会先过 `MapSensorOffset`，把「传感器右/上/前」换成「角色右/上/前」；再叠一个逐帧的 `facing`（转向对手）。所以身体上的每一个旋转都已经活在**角色坐标系**里。
- 手部基向量走的是另一条路：`HandBasis()` 只把数据从相机系换到 Unity 世界系（`wire_axes` 的 `(x,-y,-z)` + `receiver.transform`），**没有过 `sensorToModel`，也没有乘 `facing`**，然后直接交给 `LookRotation`。于是手掌保持「相机眼里的正前方」，而身体被游戏转去面向对手。
- 这局是两人对战，摄像机在侧面：人面向镜头（传感器前向），角色面向对手（模型前向），两者正好差 90°。所以掌面平行于屏幕、手腕看起来像被掰了 90°。
- 手指不受影响，因为 21 个点表达在**手自己的**坐标系里，局部形状与整体朝向无关——这也解释了为什么「手指正常、手掌歪」。

**改动**（只动坐标系，不动锚点映射与阈值）：

1. 标定（`Calibrate`）时算一次 `sensorToModel = LookRotation(modelDepth, up) × LookRotation(sourceDepth, up)⁻¹`：把传感器前向转到模型前向、以双肩为共同参考。两个前向都是「它的主人看向哪」，所以这个旋转同时把掌心朝向带对。
2. `ApplyBodyPose` 每帧把 `facing` 存进 `liveFacing`；`ApplyHands` 里手部三个轴先过 `liveFacing * sensorToModel` 再交给 `ApplyHandSkeleton`。整个手的 21 点、掌心法线、手指指向因此和身体在同一个系里。
3. 状态文件新增 `hands.frameYaw`：传感器与角色朝向的偏航差。侧面对战约 ±90，正面站位约 180——这个数就是修好之前掌面会歪掉的角度。

**没动什么**：`wire_axes` 的 `(x,-y,-z)`、`hand3d` 的 `_settle_basis` / `PALM_SIDE` / `CURL_FLOOR` 阈值、`ApplyHandSkeleton` 的轴对齐公式，一行都没改。上一轮定位的「回放每帧重置」也保持原样。

**验证**：离线 Unity 编译 0 错误；手部 58 passed / 1 skipped；全仓库 230 passed / 9 skipped；ruff 全过。Unity 侧无法在本机运行，实际掌面朝向需要重新 Play 后由 `frameYaw` 与画面确认。

## 2026-11-11 上午（三）｜翻一次掌，那只手就一直反着

**症状**（用户原话）：只有掌心朝前时皮套的手掌是对的；把手翻过来让掌背朝前，右手就不对了；再翻回来右手正常了，左手又不对。用户自己给的思路：用大拇指在左边还是右边判断是掌心还是掌背朝前，再判断哪只是左手哪只是右手。

**先量。** 这段 42.3 秒的录屏里，摄像头预览窗在 (1752,226)–(2476,816)。把这个窗口按 1.6 倍放大喂回真管线（`HandTracker(mirror_sides=True)` + `hand3d.HandLift`），每 0.1 秒取一帧，得 693 帧「手掌没有正侧对镜头、符号读得出来」的样本，对每一帧算两个数：

- `z2d` = `sign(det(粉指根 - 食指根, 中指根 - 手腕))`，只用 2D 关键点。这两个向量都躺在像平面里，它们的叉积的 z 分量就是它们的 2D 行列式——**没有任何二义性，也没有噪声可谈**。它就是 `z = x cross y` 的深度分量必须有的符号。
- `zWire` = `_settle_basis` 交出去的法线深度分量。

两个数不一致 = 皮套这只手掌心朝反了。

```
     t  side  z2d  zWire   turn  verdict   facing
  9.90 Right   -1  -0.77    0.9       ok     back
  9.93  Left   +1  +0.74   12.6       ok     palm
 10.13 Right   +1  -0.77    0.0*    FLIP     palm     <- 用户翻手
 10.13  Left   -1  +0.74    0.0*    FLIP     back
 ...   两只手到这里就再也没变过，一直到片尾
```

`0.0*` 的意思是「这一帧交出去的还是上一帧那组轴，一帧都没动」。**右手在翻手的那一帧被冻住，之后 32 秒一直保持翻手之前的掌心朝向。**

**原因：拒绝一帧，等于把那只手钉死。** `_settle_basis` 原来的规则是「跳变超过 35° 判为分支翻转，沿用上一帧」。规则本身没错（手腕确实转不了那么快），错在**被拒绝的帧不更新参考**：于是下一帧仍然拿同一个旧参考去比，仍然超 35°，仍然被拒——右手翻过去那一刻就把自己锁死了，只有等到整只手丢失超过 `HAND_GRACE` 被 `lift.reset()` 清掉才有机会解开。而「翻掌」正好就是一次 180° 跳变，是这个功能最该做对的三个动作之一。

逐帧看翻手（9.4–11.0 秒，1/30 秒采样）更清楚：右手 `zWire` 从 -0.77 直接要跳到 +0.61，跳变 92.8°；左手跳 139.6°。两只手在同一帧越线，同一帧被拒，同一帧钉死。既然两只手是**先后**被钉死的（左手先、右手后，或反过来），人就会觉得「翻过去右手坏了，翻回来右手好了但左手坏了」——错的其实是先锁的那只。

同一段录屏，两种规则各跑一遍（693 帧样本）：

| 规则 | 掌心朝反的帧 |
| --- | --- |
| 旧：>35° 拒绝、沿用上一帧 | **188 / 693（27%）** |
| 新：2D 判号 + 平滑、不拒绝 | **0 / 693** |

**改动**（`hand3d.py`，只动基向量的定号与滤波）：

1. 新增 `hand3d.palm_depth_sign(across, along)`：用 2D 关键点直接算出 `z` 的深度分量该是什么符号，返回 ±1；手掌快要正侧对镜头（投影宽/长 < `PALM_EDGE_ON = 0.15`，离变成一条线只剩 12°）时返回 0——那个姿态下掌心与它的镜像**本来就是同一张图**，此时沿用上一帧，不瞎猜。
2. `_settle_basis` 先按这个符号把实测法线摆正，再做滤波。真翻掌和噪声翻掌从此是两件事：真翻掌的符号来自画面，本来就对，一步都不用滤；噪声翻掌（world landmarks 把法线扔到手背那侧 167°）会被这个符号当场掰回来，剩下的偏差落在 `BASIS_SNAP = 10°` 以内，交给 0.5 的平滑。**所以不需要拒绝任何一帧，`BASIS_MAX_STEP` 连同那条会锁死手的规则一起删掉。**
3. `solve()` 把 `across`/`along`（已经是「掌长 = 1」的归一化量）传进 `_settle_basis`。

用户提的「看大拇指在左还是在右」和这条是同一个量：`x = 粉指根 - 食指根` 的方向就是拇指侧到小指侧的方向，拇指在哪边它就在哪边，只是它取的是两个离得最远、最不会被屈指遮住的骨头（食指根、小指根），比拇指尖稳。而且它是**逐手**判的——`flipPalmNormal` 那种一个全局开关永远只能让一只手对，这正是「一只好一只坏」的结构性来源；现在这个开关保持关闭即可。

**没动什么**：`wire_axes` 的 `(x,-y,-z)`、`PALM_SIDE`、`_frame` 的候选选择、`CURL_FLOOR` / `CURL_CEILING` / `MIN_PALM_FOOTPRINT`、`ApplyHandSkeleton` 的轴对齐公式、`sensorToModel` / `facing` 链路，以及上一轮明确要求不要碰的锚点映射，一行都没改。

**验证**：

- 同一段录屏回放：掌心朝反的帧 **188 → 0**（693 帧样本）；翻手片段逐帧 0 反号。
- 新增 3 条测试：`test_a_palm_turned_over_stays_turned_over`（真翻掌必须跟过去、并保持住，关节不许镜像）、`test_a_basis_that_contradicts_the_picture_is_corrected`（画面没变而基向量翻了，必须当帧掰回来——旧规则下这条会失败，已用重放旧规则确认）、`test_the_picture_cannot_call_a_palm_that_is_edge_on`（正侧对镜头时不下判断）。原有「翻转的基向量不许甩手腕」改成上面第二条，把「沿用上一帧」换成「按画面纠正」。
- `WireFrameTests` 补上 `yaw = π`（掌背朝镜头）：发送端与 `BindHandSkeletons` 量出来的角色手框在**掌心朝前和掌背朝前两种情况下、左右两只手**都对齐到 1° 以内——这条是「修好的数据能正确上屏」的保证。
- 手部 27 passed；全仓库 230 passed / 9 skipped；ruff 全过。
- Unity 侧本轮**没有改动**（未改 C#），无需重编译；实际效果需重新 Play 后确认：手掌在掌心/掌背两个方向都应跟手。
