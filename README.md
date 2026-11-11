# 3DDollFight

**首次克隆须知：`menuscene` 包含场景文件和菜单，但不包含 Saint Maurice / Cloud 扫描及对应预览图。** 拉取 LFS 并准备动作后，可先使用地下竞技场；取回地图转换产物后按[地图恢复说明](docs/map-assets.md)放回指定位置。各目标目录已保留 README，完整路径、大小和 SHA-256 见[资源清单](data/environments/restore-manifest.json)。本机构建与历史 `outputs/` 证据也不随 Git 分发。

3D 视觉课程的双人体感格斗项目。我们负责骨骼处理与动作识别，以及 VRM 皮套与全身动作映射。**DollFight Unity v0.10** 接入原生引擎，**Motion Lab v0.9** 保留为浏览器算法实验与对照入口。

Unity 现有街机美术升级：工业擂台、角色补光与接触阴影、面部头像、双色斜切 HUD、分段防守槽、开场/KO 演出及重赛界面；普通场地与教堂共用新版 UI，新增材质、字体和接触音效均本地加载。实现与素材来源见[对战画面说明](docs/combat-presentation.md)。

启动后先为 P1、P2 选角，再从地下竞技场、Saint Maurice、Cloud 云台中选择场地开始对战；**T** 可从对战返回选角。默认阵容为 **TRIPO / CHALLENGER**，两份旧 VRM 仍可选，支持同角色对战。选角操作、云台准备与快速复验见[街机选择说明](docs/arcade-selection.md)；模型、头像、名字和角色参数统一由[角色目录](docs/character-roster.md)管理，动作与胜负按玩家槽位独立运行。

此前角色替换验收的[普通场地录像](outputs/character-review/studio-match/review.mp4)与[教堂录像](outputs/character-review/church-match/review.mp4)均完整到达真实 KO，约 48 秒；51 项 Unity 检查通过。实际测试、性能和自动退出清理边界见[新角色验收记录](docs/character-roster-validation.md)。

Unity 当前默认展示采用 1.2 倍源速率、55 秒常规时限的 showcase 单局 KO，包含直拳、前踢、侧踹、回旋踢和腾空旋踢五类实际造成伤害的招式。当前导出在显示时间 45.58 秒由真实命中产生 KO，教堂原生连播含稳定终局实测 **48.06 秒**；生命值跨动作段连续累计。HUD、头像和玩家观察窗按主镜头中的左右位置对应角色。Motion Lab 保留旧三回合排练作浏览器对照。结算详情与原生实测见[普通战斗规则](docs/combat-rules.md)及[对战画面说明](docs/combat-presentation.md)。

## Astra 摄像头接入

本分支提供单台 Astra 控制游戏 P1 的实验场景，以及双摄骨架并排展示。首次使用请先阅读 [Astra 接入说明](integrations/astra-unity-bridge/README.md)和[中文操作指南](integrations/astra-unity-bridge/操作指南.md)，其中包含环境准备、校准和故障排查。手部 21 点骨架由独立的彩色通道估计，挂到身体骨架的手腕上驱动手指，见[手部识别说明](tools/hand_tracking/README.md)；**使用时注意双臂交叉不要超过三秒**，超过后双手会松掉、需要重开 `run.cmd` 才能恢复（原因与修法见[交付说明](docs/hand-tracking-report.md#2026-11-11-傍晚交叉不要超过三秒先把它写成规矩)）。双人实时对战尚未完成。

## Unity 入口

双击 `Start-Unity.cmd`，或用 Unity Hub 打开 `unity/`。固定 **Unity 6000.3.27f1 LTS + UniVRM 0.131.4**；展示速率与常规时限由导出的时间轴决定，设置中的 1× 表示该版本的默认节奏。默认 1440×900、16:9 画面适配，玩家视窗默认关闭；**M** 切换音效、**N** 切换震屏、**Esc** 打开设置。设置里的“排练工具”可拖动时间轴、跳到下一次交锋或跳到终局验证；跳终局会从真实终结一击前继续播放，不会直接改写 HP。新 Tripo FBX（10,880 三角面）与组员 FBX（12,200 三角面）均已接入 Humanoid；**T 打开双方选角**。已有本机构建可双击 `Play-DollFight-Unity.cmd`。骨骼算法继续由 Python/uv 管理。更多画面说明见[对战画面与操作](docs/combat-presentation.md)，工程入口见 [Unity 工程说明](unity/README.md)。

历史 Unity 三回合录像（2026-10-25）：[组员模型](data/avatars/experiments/dollfight-unity-team-20261025.mp4) · [原双 VRM 对照](data/avatars/experiments/dollfight-unity-classic-20261025.mp4) · [原生验证报告](data/avatars/experiments/unity-review-20261025.json)。原生画面直接捕获，保留移动、出拳、侧踹、回旋踢、格挡和腾空旋踢的整段过程；是公开动捕的编辑排练，尚未接 Gemini 实机输入。

**教堂场景**：外层 Saint Maurice SOG 已通过开源 Gaussian Splat 插件接入，可在教堂内部运行同一排练。已有本机构建可双击 `Play-SaintMaurice.cmd`；仅取回转换产物时，按[地图恢复说明](docs/map-assets.md)放回后用 `Start-Unity.cmd` 打开工程。`Start-SaintMaurice.cmd` 会校验并转换原始 SOG，因此需要另行取得原件。完整勘景与裁剪后的对战场景分别保存。数据准备、素材许可及碰撞边界见[教堂场景说明](docs/saint-maurice-scene.md)。

**第三场景 Cloud**：用户提供的 `cloud.ply` 已接入完整扫描，金色圆台顶面标定到世界 Y=0。两种原生构建均包含三个可选场地，使用 D3D12；选角与云台的 22 项定向测试、数据准备和原生快速复验入口见[街机选择说明](docs/arcade-selection.md)。

## 浏览器历史对照

以下浏览器说明描述 Motion Lab 的旧三回合排练和算法对照入口；它保留旧规则，不代表 Unity 当前默认的单局 KO 规则。

Windows 双击 `Start-MotionLab.cmd`，或运行：

```powershell
git lfs pull
uv sync --locked
uv run --locked python tools/fetch_avatar.py
uv run --locked python -m dollfight.server --open
```

打开 <http://127.0.0.1:18943/>。首次拉取 LFS 角色、同步 Python 依赖、下载官方对照样例需要网络；之后本机 CPU 算法与浏览器渲染均可离线运行。无需摄像头、训练服务器或 Unity。端口占用时加 `--port 18944`。

[观看最新三回合录像：完整身体分身与近景手脚](data/avatars/experiments/dollfight-self-body-20261024.mp4) · [玩家视角修订与性能对照](data/avatars/experiments/self-body-review-20261024.json) · [动作与碰撞评估](data/avatars/experiments/sparring-v09-20261024.json) · [视觉验收记录](data/avatars/experiments/sparring-v09-review-20261024.json)

v0.9 加入真实 **侧踹、腾空旋踢、踏步冲拳、Empi 连续组合、手刀架防**，保留前踢、回旋踢和拳击。三回合使用不同组合，上方“招式直达”可从完整前摇开始查看。新增护架片段替换会抬脚的拳击循环；出招骨盆保留最多 12 cm 的平滑重心偏移，继续使用膝向约束、接地 IK 与惯性衔接。腾空动作保留真实高度，60 Hz 源数据按正确速度转换。

玩家窗默认显示自身手臂和抬起的腿：保留躯干、肩臂和衣服连接的身体分身，只在本玩家窗口绘制。共享原角色骨骼、顶点与贴图，跳过头发/脸，镜头跟随头部并作近景取景调整；完整肩膀取代旧版截断四肢与淡出。骨骼包围体只剔除完全在镜头外的网格，不按脚踝高度突然隐藏腿。主画面、碰撞和衣发求解不变。参数里的“玩家视窗显示自身手脚”可即时开关。对手全身相机仍保持稳定，自身视图使用独立投影；这是屏幕格斗取景，不是已经标定的 VR 眼位或新增手指追踪。

[v0.8 腿部修正录像](data/avatars/experiments/dollfight-three-rounds-legfix-20261024.mp4) 与 [腿部对照评估](data/avatars/experiments/legs-legfix-20261024.json) 保留供回看。

本轮修复旧录像中 1.5 秒的反折站姿和 8.3 秒的交叉腿：纠正大腿轴向扭转，缩短步幅时保留膝盖弯曲平面，释放跨动作残留的脚锁，并约束过渡过冲造成的反向屈膝。完整骨骼朝向和用户报告的时刻均加入回归检查。[旧 90 秒录像](data/avatars/experiments/dollfight-three-rounds-v08-20261024.mp4) 保留作失败对照；原先的骨长与支撑速度自检没有覆盖这些人体姿态错误。

Motion Lab 的旧默认模式为 **三回合 / 90 秒双人排练**，显示本地绑定 Tripo 皮套的手、颈与发束重建版。两路动作独立编排，第三回合以腾空旋踢收尾；它是公开真人动捕的编辑排练，尚不是实时相机双人游戏或自主对手。

主场景默认放大并开启三视角；“从头播放”“第 1/2/3 回合”“录制完整演示”可直接使用。录制保存当前三个实时 WebGL 画面与回合/血量/距离，保持画面比例。选择“显示参数”可以切换原网格、授权底模、旧版无约束步法、慢放及算法开关。具体检查：

1. 看 0–2、5–7、10–13、20–23 秒的步法：短步后回架，根轨迹不随片段积累偏到场外；支撑脚做 IK，未抹掉上身借力。
2. 看约 9、14、25 秒及下一回合的反侧高踢，检查裙摆抬起、回落和转髋；暂停/倒拖会重置实时衣发，不能替代连续播放检查。
3. 切“皮套近看”检查握拳、前臂/袖口、颈部/脸部接缝与发束。手型由动作先验驱动，19 关节输入没有手指追踪。
4. 看两个玩家窗：显示对手全身与自身出招手脚。关闭自身手脚可对照主画面是否保持一致；“严格眼位实验”仍需要物理屏幕尺寸、位置和眼位标定。
5. “显示参数”中的 12 秒测量记录实际动画帧占比、CPU 姿态/衣发/提交成本和三视角三角面数量；模型面数与贴图精度保留。

裙布使用姿态修正形状、216 点动态控制网格与最多 25 mm 的连续表面修正。高踢比旧版更可读，但极端前踢腰口仍有穿插；不是通过衣物碰撞验收的成品。模型形象、美术细节与角色相似度也仍待验收。[皮套对照页](http://127.0.0.1:18943/avatar-review.html) 作为辅助，主要视觉评价在 DollFight 主场景完成。

**真人动作的参考攻击时序与规则识别结果分别保存、显示。** 原始动捕不经过人为抬肢体再整体旋转；识别器不读取片段名称或参考标签。旧合成对练保留在下拉框中用于逻辑回归，不能作为动作质量的证据。

## 已实现与边界

| 部分 | 当前交付 |
| --- | --- |
| 骨架处理 | 米制坐标、相机适配、标定、置信度门限、One Euro、缺失预测、固定骨长、关节限位 |
| 全身映射 | 独立骨盆/胸腔朝向，保留躯干扭转；肘膝弯曲平面；按腿长缩放、接地与双骨 IK |
| 动作识别 | 基础拳/膝/踢/蹲/侧倾、回旋踢、转身、护架、拨挡与组合规则；提膝候选延迟，防止踢腿前摇误报膝击；踢腿配合摆臂不再算独立出拳 |
| 皮套 | 两份高面数 Tripo 网格本地绑定；54 Humanoid、216 衣物控制骨；默认重建版保留作者 59 发骨 / 12 发束及手指权重；原件/重建对照。另保留约 3.9 万面的授权底模；不是 SkinTokens 推理输出 |
| 动作衔接 | 双人根轨迹、短步步幅编辑、0.30 s 惯性衔接、脚 IK、支撑脚朝向约束与连续接地修正；旧三回合组合保留对照 |
| 实时渲染 | GPU 蒙皮；粗控制网格驱动细裙面；不再逐骨递归更新全部后代；可见视图调度、审计降频、避免重复法线计算；可测实时衣发和缓存回放 |
| 交互验证 | 动捕/骨架/模型对照、逐帧、慢放、噪声消融、全身玩家视窗、实际影响伤害与出招的前后摇 |
| Unity 接入 | [原生工程与启动步骤](unity/README.md)：UniVRM 加载、Humanoid 映射、同步双人回放、第一人称网格、原生衣发更新、对战场景与构建入口 |

浏览器 VRM 路线已可运行。本机已安装 Unity Editor 与 Hub，并确认免费 Personal 许可有效；Unity 的实际编译、播放与视觉验证状态单独记录在 [Unity 工程说明](unity/README.md)，不能以 Python/浏览器测试代替。

仍未完成：Gemini 实机输入、实时双人同步、基于大量真人数据的分类器、自然的任意招式过渡/受击动画、正式角色资产和大招库。这里保留真人全身运动，而非肌肉/动力学仿真。位移放大和对战边界仍可能造成滑步；动作检查视图保留采集根位移，便于直接发现这一问题。浏览器旧三回合模式的 P2 为独立编排；其他旧单人片段仍用延迟回放，均不能当成实时对手。

## 验证与协作

```powershell
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python tools/check_contracts.py
uv run --locked python tools/check_unity_scripts.py
node apps/motion-lab/tests/run-tests.js
```

最后一条在编辑器之外类型检查 Unity 脚本：Unity 开着工程时它拒绝批处理编译，此前 C# 改动只能靠人眼复核；现在用 .NET SDK 引用同一批引擎程序集，两秒出结果，能报到文件与行号。它只校验类型，不能替代在编辑器里跑一遍。

Python 3.10.19、uv ≥0.9.17、依赖由 `uv.lock` 固定。Node 22+ 用于投影测试（可选 Tripo CLI 与演示解耦）；启动界面不需要 npm。浏览器依赖、许可证和 SHA-256 在 `apps/motion-lab/vendor/`，公开动捕的原始哈希在每个样本内；VRM 用 [下载清单](data/avatars/sample.json) 固定，10.8 MB 文件保存在忽略目录。

- [当前实现、失败边界与验收方法](docs/motion-lab.md)
- [手部追踪交付说明：现状、使用说明、开发日志](docs/hand-tracking-report.md)
- [手部识别技术大纲](docs/hand-tracking.md)
- [Unity 导入与回放交接](unity/README.md)
- [皮套路线更换、制作与验证记录](docs/avatar-pipeline.md)
- [v0.8 三回合位移与接触评估](data/avatars/experiments/sparring-v08-20261024.json)
- [v0.8 高踢密集裙面接触与局部变形评估](data/avatars/experiments/garment-v08-20261024.json)
- [v0.7 历史动态截图、模型哈希和三窗性能记录](data/avatars/experiments/local-rig-review-20261024.json)
- [Git 与 uv 协作规范](CONTRIBUTING.md)
- [跨组协议](docs/contracts.md)、[JSON Schema](src/dollfight/schemas/)、[协议样例](tests/fixtures/)
- [动捕来源与致谢](data/samples/README.md)

远端为 [PoesisQ/3DDollFight](https://github.com/PoesisQ/3DDollFight)；本分支为 `梅大帅`，在 `menuscene` 的游戏工程基础上继续接入 Astra 摄像头。
