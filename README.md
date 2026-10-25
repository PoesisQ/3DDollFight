# 3DDollFight

3D 视觉课程的双人体感格斗项目。我们负责骨骼处理与动作识别，以及 VRM 皮套与全身动作映射。**DollFight Unity v0.10** 接入原生引擎，**Motion Lab v0.9** 保留为浏览器算法实验与对照入口。

## Unity 入口

双击 `Start-Unity.cmd`，或用 Unity Hub 打开 `unity/`。固定 **Unity 6000.3.27f1 LTS + UniVRM 0.131.4**，使用 90 秒双人真人动捕排练和三个观察视窗。已接入组员提供的 FBX（含手指、12,200 三角面），**T 切换 FBX / 原霙 VRM**；已有本机构建可双击 `Play-DollFight-Unity.cmd`。修正长时间前俯护架，增加落脚朝向约束、姿态引导裙布和独立的近景手臂 IK。骨骼算法继续由 Python/uv 管理。完整启动、协作与验证边界见 [Unity 工程说明](unity/README.md)。

[观看 Unity 完整三回合：组员模型](data/avatars/experiments/dollfight-unity-team-20261025.mp4) · [原双 VRM 对照](data/avatars/experiments/dollfight-unity-classic-20261025.mp4) · [原生验证报告](data/avatars/experiments/unity-review-20261025.json)。原生画面直接捕获，保留移动、出拳、侧踹、回旋踢、格挡和腾空旋踢的整段过程；是公开动捕的编辑排练，尚未接 Gemini 实机输入。

## 浏览器历史对照

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

默认进入 **DollFight 三回合 / 90 秒双人排练**，显示本地绑定 Tripo 皮套的手、颈与发束重建版。两路动作独立编排：短步接近、退步让距、侧移、拳击、前踢、回旋踢、侧踹、护架与连续套路，第三回合以腾空旋踢收尾。命中、格挡、挥空和前后摇由时序与空间接触结算。它是公开真人动捕的编辑排练，尚不是实时相机双人游戏或自主对手。

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
| 动作衔接 | 三回合双人根轨迹、短步步幅编辑、0.30 s 惯性衔接、脚 IK、支撑脚朝向约束与连续接地修正；旧组合保留对照 |
| 实时渲染 | GPU 蒙皮；粗控制网格驱动细裙面；不再逐骨递归更新全部后代；可见视图调度、审计降频、避免重复法线计算；可测实时衣发和缓存回放 |
| 交互验证 | 动捕/骨架/模型对照、逐帧、慢放、噪声消融、全身玩家视窗、实际影响伤害与出招的前后摇 |
| Unity 接入 | [原生工程与启动步骤](unity/README.md)：UniVRM 加载、Humanoid 映射、同步双人回放、第一人称网格、原生衣发更新、对战场景与构建入口 |

浏览器 VRM 路线已可运行。本机已安装 Unity Editor 与 Hub，并确认免费 Personal 许可有效；Unity 的实际编译、播放与视觉验证状态单独记录在 [Unity 工程说明](unity/README.md)，不能以 Python/浏览器测试代替。

仍未完成：Gemini 实机输入、实时双人同步、基于大量真人数据的分类器、自然的任意招式过渡/受击动画、正式角色资产和大招库。这里保留真人全身运动，而非肌肉/动力学仿真。位移放大和对战边界仍可能造成滑步；动作检查视图保留采集根位移，便于直接发现这一问题。默认三回合的 P2 为独立编排；其他旧单人片段仍用延迟回放，均不能当成实时对手。

## 验证与协作

```powershell
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python tools/check_contracts.py
node apps/motion-lab/tests/run-tests.js
```

Python 3.10.19、uv ≥0.9.17、依赖由 `uv.lock` 固定。Node 22+ 用于投影测试（可选 Tripo CLI 与演示解耦）；启动界面不需要 npm。浏览器依赖、许可证和 SHA-256 在 `apps/motion-lab/vendor/`，公开动捕的原始哈希在每个样本内；VRM 用 [下载清单](data/avatars/sample.json) 固定，10.8 MB 文件保存在忽略目录。

- [当前实现、失败边界与验收方法](docs/motion-lab.md)
- [Unity 导入与回放交接](unity/README.md)
- [皮套路线更换、制作与验证记录](docs/avatar-pipeline.md)
- [v0.8 三回合位移与接触评估](data/avatars/experiments/sparring-v08-20261024.json)
- [v0.8 高踢密集裙面接触与局部变形评估](data/avatars/experiments/garment-v08-20261024.json)
- [v0.7 历史动态截图、模型哈希和三窗性能记录](data/avatars/experiments/local-rig-review-20261024.json)
- [Git 与 uv 协作规范](CONTRIBUTING.md)
- [跨组协议](docs/contracts.md)、[JSON Schema](src/dollfight/schemas/)、[协议样例](tests/fixtures/)
- [动捕来源与致谢](data/samples/README.md)

远端为 [PoesisQ/3DDollFight](https://github.com/PoesisQ/3DDollFight)，当前工作分支 `feat/motion-lab`。
