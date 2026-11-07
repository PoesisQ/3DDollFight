# Saint Maurice 教堂场景

**本分支不上传教堂扫描及预览图。** `.unity` 场景与目标目录内的恢复说明会随仓库分发；取回已转换的 `church.spz` 后，按[地图恢复说明](map-assets.md)放回即可。`church-full.spz` 仅在打开完整勘景场景时需要。大小、SHA-256 和精确目标路径见[资源清单](../data/environments/restore-manifest.json)。

外层 `Parish Church of Saint Maurice.sog` 已接入 Unity，可在教堂内部播放双人动捕排练。当前默认 showcase 为单局 KO、55 秒常规时限；画面按 16:9 适配，默认使用 1440×900，玩家视窗默认关闭。它是 Gaussian Splat 扫描，Unity 默认只把 SOG 识别为 `DefaultAsset`，不能直接当 FBX 或普通场景打开。规则和操作见[普通战斗规则](combat-rules.md)与[对战画面说明](combat-presentation.md)。

渲染使用 MIT 开源的 [UnityGaussianSplatting](https://github.com/aras-p/UnityGaussianSplatting)，固定上游提交 `0cc0bf8bb0e9af75ff1c002592024f86057ced58`、包版本 2.0.0，嵌入 `unity/Packages/org.nesnausk.gaussian-splatting/`。本地只增加相机层过滤，避免在自身手脚的叠加相机重复画教堂。格式转换使用 [PlayCanvas splat-transform](https://github.com/playcanvas/splat-transform) 3.10.3，依赖及锁文件在 `tools/splat-transform/`。

## 启动和编辑

已有本机构建时双击根目录 **`Play-SaintMaurice.cmd`** 打开独立程序。Space 暂停、R 重播、T 切换角色；**M** 切换音效、**N** 切换震屏、**Esc** 打开设置。玩家视窗默认关闭，可在设置中切换。设置 → 排练工具提供时间轴、下一次交锋和跳到终局；跳终局会从真实终结一击前继续结算。默认 showcase 按 1.2 倍源速率播放，HP 连续；55 秒常规时限内未 KO 会进入加时，具体节奏读取动作导出。

已有原始 SOG 时，双击 **`Start-SaintMaurice.cmd`** 准备本地数据并打开 Unity 场景，进入 Play Mode 查看。只有已转换文件时，直接恢复文件，再用 **`Start-Unity.cmd`** 打开工程并选择教堂，或直接打开 `Assets/Scenes/SaintMauriceDuel.unity`；不要运行要求原件的 `Start-SaintMaurice.cmd`。两个场景分别是：

| 场景 | 内容 | 扫描点数 | 渲染球谐阶数 |
| --- | --- | ---: | ---: |
| `SaintMauricePreview.unity` | 完整扫描，供勘景 | 9,975,598 | SH3 |
| `SaintMauriceDuel.unity` | 祭坛前的格斗场地、两角色、可选玩家视窗 | 4,607,577 | SH1 |

Unity 菜单 **DollFight → Saint Maurice → Open Church Duel** 打开现有场景；**Build Church Duel** 输出到 `outputs/saint-maurice/duel/DollFightChurch.exe`，包含三个对战场地。若要使用根目录的两个 `Play-*` 启动器，应选择 **DollFight → Build Windows Demo**，它输出到启动器共用的 `outputs/arcade-select/DollFight.exe`。恢复地图或修改规则后需重新构建；独立程序不随克隆分发。**Create Scan Preview / Create Church Duel** 会重新生成对应场景，会先询问是否保存当前修改；已有场景编辑应使用 Open。

Windows 使用 **Direct3D 12**，启动脚本已加 `-force-d3d12`。此插件不支持 Direct3D 11 或 MSAA，因此项目默认抗锯齿设为关闭；原 `DollFight.unity` 运行时仍使用自身的 4× MSAA 配置。补充的 Unity VR/XR 内置模块用于满足插件编译依赖。

## 数据与重建

已取得转换产物时直接按[地图恢复说明](map-assets.md)放回；下面仅用于从原件重建。原始 SOG 默认位于仓库上一级目录 `../Parish Church of Saint Maurice.sog`，未修改。运行：

```powershell
uv run --locked python tools/prepare_saint_maurice.py
# 源文件在其他位置时：
uv run --locked python tools/prepare_saint_maurice.py --source 'D:\path\Parish Church of Saint Maurice.sog'
```

脚本校验源文件 SHA-256，以 Node.js 22+ 转成 SPZ v4；首次会安装锁定的转换器。后续校验配置和两个 SPZ 的哈希，匹配时直接使用缓存。强制重建可加 `--force`。本机转换完整扫描约 66 秒、最高约 7.2 GB CPU 内存，双人场地约 28 秒、4.7 GB；不同机器耗时会不同。

完整扫描保存在 `Assets/LocalScenes/SaintMaurice/church-full.spz`（约 194 MB），不随游戏重复打包；对战扫描保存在 `Assets/StreamingAssets/Environments/SaintMaurice/church.spz`（约 91 MB）。两个文件均保留源 SH3 数据，对战场景选择 SH1 渲染。`provenance.json` 记录配置、原件和输出哈希，`ATTRIBUTION.txt` 保留源署名。

裁剪参数、来源和源哈希在 `data/environments/saint-maurice.json`。转换器的裁剪坐标使用 PlayCanvas 引擎空间，与 PLY/SPZ 源坐标相差绕 Z 轴 180°；配置同时记录两种坐标。Unity 根节点通过 Y 反射扶正扫描，格斗场景平移到祭坛台阶前的平地；比例目前按视觉对齐，尚未做现场尺寸标定。

## 历史本机验证（2026-11-06）

以下记录对应 2026-11-06 的旧三回合、三视窗版本，分辨率与当前默认画面不同，不作为当前 KO 版本的构建或性能验收。Unity 6000.3.27f1 编译、Editor Play Mode 和 Windows Development 构建均已执行。独立程序使用 RTX 3060 Laptop GPU / Direct3D 12，在 1280×1000、VRM + 组员 FBX、三个视窗、SH1、关闭 MSAA 的条件下预热并截图，再连续测量 90.02 秒：**平均 21.94 FPS，帧时间 P95 为 49.27 ms，1,975 帧中非有限骨骼数据帧为 0**。测量时关闭 Unity Editor，未录制视频。该历史版本的三视角扫描渲染未达到 60 FPS。

本机证据保存在忽略目录：`outputs/saint-maurice/review/performance.json`、`duel-04.1.png`、`duel-13.7.png`、`duel-84.2.png`，覆盖护架、侧踹和第三回合腾空旋踢；运行日志为 `outputs/saint-maurice/native-player.log`。复验时可给独立程序传入 `-churchReview <绝对输出目录> -churchReviewSeconds 90`，自动预热、定点截图和测量；采样期间不要操作回放或调整窗口。

## 后续开发边界

场地已添加 6×2 的地面碰撞盒与四面边界。当前 Unity 角色播放离线动捕排练，移动不会自动受到这些碰撞盒约束；尚未接入实时双人输入。扫描没有普通三角网格碰撞，也不接收角色的动态阴影；桌椅、台阶等需要单独搭简化碰撞体。

源作品为 Pavel Tanhäuser 的 [Parish Church of Saint Maurice](https://superspl.at/scene/15a202e6)，内附许可为 **CC BY-NC-ND 4.0**：要求署名、禁止商业使用、禁止分发修改版本。转换及裁剪文件、本机包含扫描的构建均留在忽略目录中，不提交或对外发布；开源插件的 MIT 许可不覆盖扫描素材。需要公开发布项目时应先取得素材授权或替换场景。
