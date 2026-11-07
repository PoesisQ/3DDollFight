# DollFight Unity

**首次克隆不含 Saint Maurice / Cloud 的扫描和场地预览图。** 场景文件、选角菜单和地下竞技场预览图已提交。先拉取 LFS 并生成动作，可使用地下竞技场；地图到手后按[地图恢复说明](../docs/map-assets.md)放回，目标目录内也有 README。完整教堂扫描只用于勘景，不是普通对战的必需文件。

当前画面加入工业擂台、角色照明与脚下接触阴影、角色头像、双色街机 HUD、分段防守槽、READY/FIGHT 与 KO 演出及重赛操作。普通版和教堂版共用界面；字体、材质、短音效随包离线加载，来源和复验方式见[对战画面说明](../docs/combat-presentation.md)。

默认 P1 为用户提供的 Tripo B9E9 角色，P2 为紫色 CHALLENGER。启动先打开双人选角，确认角色后选择地下竞技场、Saint Maurice 或 Cloud 云台；四个角色通过同一[角色目录与双槽选择接口](../docs/character-roster.md)加载。模型、HUD 名字、头像及结算随选择同步；完整操作与云台准备见[街机选择说明](../docs/arcade-selection.md)。

战斗呈现已加入 [16:9 取景、双血条与命中反馈](../docs/combat-presentation.md)。默认 showcase 以 1.2 倍源速率播放，常规倒计时 55 秒，包含直拳、前踢、侧踹、回旋踢和腾空旋踢五类实际造成伤害的招式；当前导出在显示时间 45.58 秒真实 KO，教堂原生连播含稳定终局实测 **48.06 秒**。血量持续累计，时间到后未 KO 则加时。显示时限与默认速率读取导出的时间轴。V 开关玩家观察窗，Esc 打开设置，M / N 分别开关音效与震屏；设置内保留调试跳转。普通和教堂启动器使用 1440×900 窗口。

HUD 根据主镜头投影确定左右角色：普通场地 P1 在左，教堂反向取景时 P2 在左。名字、头像、生命、防守、胜场和接触提示整组对应，玩家观察窗及自身手脚窗口使用同一侧别映射；动作短暂交叉时保持布局稳定。P1 粉红、P2 冰蓝和真实赢家身份始终不变。

普通攻击使用统一的 [碰撞、伤害和胜负规则](../docs/combat-rules.md)。HUD 显示单局倒计时、防守槽和 KO 结算；**B** 切换标准判定体，**R / 重新开始** 重播，结束后保留最终结果。修改 Python 规则后先运行 `tools/prepare_unity.py` 再构建，已有独立程序不会自动读取新的源代码。

`unity/` 现在是完整工程的入口，使用 **Unity 6.3 LTS / 6000.3.27f1**、Built-in Render Pipeline、**UniVRM 0.131.4**。骨骼处理、动作识别和回放编排继续由 `uv` 管理的 Python 实现；Unity 负责 Humanoid 导入、GPU 蒙皮、材质、衣发更新与多视角显示。浏览器 Motion Lab 保留为算法检查与对照工具。

## 启动

1. 安装 `ProjectSettings/ProjectVersion.txt` 指定的 Editor，在 Unity Hub 登录并激活免费 Personal 许可。
2. 仓库根目录双击 `Start-Unity.cmd`。脚本拉取 LFS、同步 uv 依赖并生成两个人物与同一时钟的单局 KO 回放，然后打开工程。
3. 首次打开等待 Package Manager 和 C# 编译完成。若没有自动生成场景，选择 **DollFight → Create Duel Demo Scene**，打开 `Assets/Scenes/DollFight.unity` 后按 Play。
4. 先选双方角色，再确认场地。P1 用 WASD / F，P2 用方向键；Tab 切当前玩家，Enter 确认，也可用鼠标。Esc 返回上页或取消确认。对战中 Space 暂停，R 从头播放，V 开关玩家窗，H 开关自身手脚，**T 返回双方选角**，Esc 打开设置；设置中的排练工具支持慢放和跳转。

已有本地构建时，双击 `Play-DollFight-Unity.cmd` 打开原生选角入口。更新代码或资产后，在编辑器菜单 **DollFight → Build Windows Demo** 重新构建；三个对战场景须均已准备，构建保留已有场景，不重建覆盖组员的场景编辑。两种启动器共用 `outputs/arcade-select/DollFight.exe`，使用 Direct3D 12；教堂启动器只改变选场页默认值，仍从角色选择开始。构建属于本地生成产物，不随 Git 克隆分发。

Saint Maurice 教堂使用独立的 `SaintMauriceDuel.unity` / `SaintMauricePreview.unity`。已有转换文件时直接按[地图恢复说明](../docs/map-assets.md)放回，再用 `Start-Unity.cmd` 打开工程并选择教堂，或打开现有场景；不需要重新 Create 场景。`Start-SaintMaurice.cmd` 会先运行准备脚本，需要原始 SOG；`Play-SaintMaurice.cmd` 需要另行构建的本机程序。[教堂场景说明](../docs/saint-maurice-scene.md) 记录开源插件、SOG 转换、Direct3D 12 要求和素材来源。

编辑器不在默认位置时设置 `DOLLFIGHT_UNITY_EDITOR` 为本机 `Unity.exe` 路径。不要把机器路径写入项目 manifest。也可以手动执行：

```powershell
git lfs pull
uv sync --locked
uv run --locked python tools/prepare_unity.py
# 在 Unity Hub 添加本仓库的 unity 文件夹并打开
```

首次拉取资产需要 Git LFS，其他依赖解析需要 Unity Package Registry。UniVRM 的同版本官方发布包已经校验后重打包为 `Vendor/*.tgz`，通过 LFS 固定；源文件与 GUID 不变，附带官方 MIT 许可及来源哈希，避免每人打开工程时重新克隆整个上游仓库。可用 `tools/package_univrm.py` 从官方发布包重复生成。网络失败时先检查 Package Manager 日志；不要关掉 TLS 校验或随意升级包。

## 实现与边界

`HumanoidReplay` 调用官方 `Vrm10.LoadPathAsync`，验证有效的 Unity Humanoid 和 19 个关节，再从 T-pose 捕获各骨骼 bind 世界旋转。每帧应用 canonical 骨架的全局旋转增量，再乘导入骨架的 bind 旋转；额外上胸与肩节点由实际父链处理。

**VRM 1.0 的 UniVRM 导入采用 X 反射**：位置 `(-x,y,z)`，四元数 `(x,-y,-z,w)`。这与某些 glTF 加载器的 Z 反射不同。旧适配器的 Z 反射已纠正，测试同时检查旋转交换律和实际导入轴约定。

`export_duel` 把双方转向与对战世界位置写进回放。世界根位置只添加一次，P2 的片段索引映射到共享时间轴。水平位移始终是场地米制坐标，不乘 FBX 导入缩放；垂直蹲起/跳跃按腿长映射并保留目标站立髋高。新 FBX 在 T-pose 从真实蒙皮表面选取鞋底支撑点，按源动作的接地高度和权重调整骨盆/双腿 IK，飞行时释放；不以脚踝骨的固定高度代替鞋底。准备脚本以两份 hybrid 的共同 T-pose 为中间骨架；任意体型的接触精度仍需独立验证。

准备脚本显式采用 showcase 的 **1.7 m 初始间距 / 1.0 倍位移参数**，旧 `legacy` 编排保留 1.8 m 初始间距，避免误用通用摄像头站位的 2.2 m 默认间距而让整段攻击挥空。默认 showcase 导出校验实际 KO、双方均有命中、五类伤害招式及一分钟内展示预算；来源记录同时保存命中、格挡、挥空与血量。新 FBX 目前显示的是同一标准骨架判定的结果，还没有按其盔甲外轮廓重新拟合命中体。

组员 FBX 保存在 `Assets/Art/TeamCharacter/`，原网格 **12,200 三角面 / 67 个蒙皮骨骼**，有手指；FBX 和两张原纹理通过 LFS 管理。`TeamCharacterImport` 配置 Humanoid，应用 ModelImporter 已求出的 T-pose，再生成 `Assets/Resources/TeamCharacter.prefab`，没有把原 A-pose 误当 T-pose。原件哈希见同目录 `provenance.json`。后续替换 FBX 后执行 **DollFight → Prepare Team Character** 并复验；外部授权信息须由素材提供者补充，不将它标为 CC0 或项目自制角色。

`FirstPersonBody` 在载入时提取连续手臂/腿网格，复用材质与贴图，省去头发、头颈、胸部与裙子在个人视角的绘制。一个只含 Transform 的显示骨架复制已求解的姿态；近景双骨 IK 仅在这份副本上把贴眼护架下移、前送，完整肩臂端点留在眼位之后。新 FBX 的大肩甲另外通过显示肩根后移 16 cm、下移 12 cm 留出视野，原手部目标与腿部位置保留。没有第二份 Animator、布料、发束或碰撞求解。全局角色和命中骨架不被近景修正写入。对手取景与自身取景使用不同投影；这是屏幕游戏取景，不是已标定的 VR 眼位。H 可关掉自身手脚作对照。

人体姿态之后手动调用 UniVRM runtime，驱动原有头发弹簧。裙子保留原细网格，用 24 条宽幅姿态引导控制轮廓，再用原生 Cloth 给 216 个控制点加入次级运动；腰圈固定，裙摆相对引导的最大位移从错误的 65 cm 收紧至 4.5 cm。引导结合大腿抬起方向和重力方向，避免躯干侧倾时整条裙子一起翻上去。开启腿胶囊、虚拟粒子、连续碰撞及控制点自碰撞。它是美术形状约束与物理次级运动的组合，仍没有密集网格三角形无穿透保证，极端腰口、袖口和生成网格局部缺陷仍需修形。VRM 身体/手部/头发改用有光照的材质以显示体积；不削减原模型面数或贴图分辨率。

动作编排修正：原待机误用了 CMU 下潜动作的 30° 前俯片段，现改用短拳击护架；招式按原速或轻微压缩播放，空余时间回架，不再把前摇拉长填满交换时间；旋踢补全落地回收。惯性过渡为 0.30 s。脚的朝向锁与位置锁分开：稳定鞋底缓解地面扭动，脚尖抬起、离地或快速轴转时立即释放，保留回旋踢支撑脚的真实转动，而不是按根位移方向强转脚尖。

旧排练中部分“碰到却不掉血”的主要原因是动画与出招锁定不同步：规则因后摇或受击硬直拒绝了攻击，编排动画仍继续播放击打。默认 showcase 改用完整的单次拳击摘录与单次踢击轮流编排，保留前摇、有效期和回收间隔；当前导出没有 recovery 拒绝或取消的攻击。通用伤害规则与判定体大小保持原值，具体判定见[普通攻击规则](../docs/combat-rules.md)。

手指闭合是显示先验，不是 19 关节输入推导出的真实手指跟踪。默认展示仍由公开 CMU 动捕编排，浏览器保留旧三回合排练；尚未接通 Gemini 实机和实时双人传输。换 Unity 不会自动修复生成模型的面部、拓扑或动作质量。

## 历史三回合录像与实测（2026-10-25）

[组员 FBX 的完整三回合](../data/avatars/experiments/dollfight-unity-team-20261025.mp4) · [原双 VRM 的完整三回合](../data/avatars/experiments/dollfight-unity-classic-20261025.mp4) · [来源、帧采样与验证报告](../data/avatars/experiments/unity-review-20261025.json)。两段均为 1280×1000 / 30 fps、约 90 秒，保留所有准备、移动、回收和过渡；画面有明确的非实时相机采集标记。

在 RTX 4060 Laptop GPU 上，Windows Development 独立程序、三视窗和两路自身手脚、4× MSAA、阴影、原网格与贴图，**关闭录制后**各跑 90 秒。Editor 开着但停止 PlayMode；普通桌面/agent 工具仍开着，并非隔离实验室环境。两次都没有非有限骨骼数据帧。

| 模型 | 平均 FPS | 帧时间中位数 | 帧时间 P95 | 最长单帧 |
| --- | ---: | ---: | ---: | ---: |
| 希美 VRM + 组员 FBX | 93.0 | 10.11 ms | 14.47 ms | 40.58 ms |
| 希美 + 霙 VRM | 58.0 | 16.30 ms | 23.24 ms | 45.88 ms |

这不是相机到显示器的端到端延迟，也未验证低配置电脑。录像中的 FPS 还包含编码开销，不能用来替代上表。当时的旧排练结算有 8 次命中、10 次格挡、4 次挥空和 6 次因前后摇未提交的攻击；三回合结算血量为 88/88、86/72、100/70。这些数值不代表当前 showcase 短局。新 FBX 的模型差异目前不改变标准骨架的命中体。

优先回看约 4 秒的护架/自身手臂、13–15 秒侧踹、43–45 秒转髋与架防、83–87 秒腾空旋踢及落地。高踢的裙摆轮廓比原塌陷版本连续，但仍有腰口、袖口和生成网格的局部穿插/黑边；近景手指与组员模型的大肩甲也没有达到成品美术质量。

## 验证

当前 showcase 的节奏、侧别与原生验收记录见[对战画面说明](../docs/combat-presentation.md)，新结果保存在 `outputs/showcase-review/`；`outputs/arcade-polish/` 保留前一版美术升级记录。以下为 2026-10-25 历史验证：本机已安装上述 Editor 与 Hub，免费 Personal 许可已确认有效；**131 项 Python 回归检查、6 项 Unity EditMode 检查**、Editor 编译和 Windows 构建通过。检查涵盖脚朝向锁的轴转/起跳释放、非深蹲护架、FBX 的有效 Humanoid 与 T-pose、双骨 IK 保持骨长/末端朝向，以及模型缩放不得改变水平场地位移。官方 CLI 已实际执行场景打开、播放、停止、截图、测试和构建。

2026-10-25 的九个定点用 Unity `BakeMesh(mesh, true)` 独立检查新 FBX 的完整表面最低高度，范围为 **−1.97 mm 至 +5.52 mm**（这些时刻 P2 有支撑脚）。这是少量静态采样，不是整段连续的脚滑/接地证明。实际执行个人显示 IK 前后，全局 19 骨的位置和旋转差均为 0。

这些检查不提供“动作自然度”或“零穿模”评分。当前展示需连续查看完整短局，历史三回合需使用对应旧回放，并在原 VRM 和组员 FBX 之间对照；新 FBX 的头饰、长尾装饰尚无独立的布料/发束骨，当前跟随其原蒙皮。手指仍是显示先验，生成服装的语义分区和高踢腰口仍是已知限制。

复验入口：

- EditMode Test Runner：`DollFight.Humanoid.Tests`。
- 批处理创建场景：`-executeMethod DollFight.Editor.DemoBuild.CreateScene`。
- Windows 构建：`-executeMethod DollFight.Editor.DemoBuild.BuildWindows`，输出到忽略目录 `outputs/arcade-select/`；可用 `-dollfightBuildOutput <exe绝对路径>` 指定其他输出目录。
- 运行时加 `-dollfightCapture <绝对目录>` 可抓取旧三回合的固定源时间采样；当前短局使用 `-dollfightPresentationReview <绝对目录>` 检查开场、侧别、接触与终局，并连续播放检查完整展示。
- `-dollfightBenchmark <绝对 JSON 路径>` 在预热后测量 90 秒真实运行帧时间；测量时不要同时录制。
- `-dollfightRecordReview <绝对目录> -dollfightFfmpeg <已安装 ffmpeg.exe 的绝对路径>` 自动录制完整回放为 `review.mp4`。`-dollfightClassic` 改为两份 VRM；`-dollfightRecordSeconds 5` 可先做短片验证。目录中的 `capture.json` 记录采集帧与重复帧数量，`complete.json` 记录回放与墙钟时长。

录制使用 Unity 的 [ScreenCapture + AsyncGPUReadback](https://docs.unity3d.com/6000.3/Documentation/ScriptReference/ScreenCapture.CaptureScreenshotIntoRenderTexture.html) 捕获已经合成的游戏画面，并在工作线程送给本地 FFmpeg；帧缓冲池与有界队列限制内存增长。仍按实时速度游玩，30 fps 视频漏采时重复上一帧并计数，不离线慢放动作来伪装性能。Windows GDI 录屏在本机 DX12 下曾得到冻结画面，因此不作为交付证据。FFmpeg 为可选本机工具，不随 UPM 包分发。

`com.unity.pipeline` 固定为 `0.9.1-exp.1`，供官方 Unity CLI 连接编辑器。它让 agent 通过正式命令检查、播放和截图，不要求把项目上传到云端。CLI 与编辑器安装在机器环境中，不由 uv 安装。

## 协作与来源

提交 `Assets` 及 `.meta`、`Packages/manifest.json`、`packages-lock.json` 和 `ProjectSettings`；保留资源 GUID，不提交 `Library/Temp/UserSettings`。本地生成的 `Assets/StreamingAssets/DollFight/` 不提交，权威模型仍是 `data/avatars/local/*-hybrid.vrm` 的 LFS 资产，准备脚本记录 SHA-256。新克隆须先运行准备脚本。

`Packages/com.dollfight.humanoid/` 是可独立交接的嵌入 UPM 包。接入其他团队工程时合并 `manifest.fragment.json`，调整本地包路径，不覆盖原有依赖；两边采用同一 Editor/UniVRM 版本后再验证。

官方依据：[Unity 6 LTS 支持](https://unity.com/releases/unity-6/support)、[UniVRM v0.131.4](https://github.com/vrm-c/UniVRM/releases/tag/v0.131.4)、[Unity CLI](https://docs.unity.com/en-us/unity-cli/use-unity-cli)、[Pipeline 包](https://docs.unity.com/en-us/unity-cli/unity-pipeline/unity-pipeline-package)。模型许可与代码依赖许可分别管理。

本轮方法参考：[Unity Cloth 的粒子、碰撞和约束](https://docs.unity3d.com/6000.3/Documentation/Manual/class-Cloth.html)、[双骨 IK 的位置、朝向和弯曲提示](https://docs.unity3d.com/Packages/com.unity.animation.rigging@1.3/manual/constraints/TwoBoneIKConstraint.html)、[VRM 第一人称网格划分建议](https://vrm.dev/en/univrm/firstperson/univrm_firstperson/)、[Epic 第一人称专用投影与世界表示](https://dev.epicgames.com/documentation/en-us/unreal-engine/first-person-rendering)。本项目采用这些设计原则在现有 Unity 工程实现，没有声称接入 Unreal 的渲染代码。
