# 3DDollFight

3D 视觉课程的双人体感格斗项目。**Motion Lab v0.4** 将我们负责的两部分放在一个可检查的原型中：骨骼处理与动作识别，以及 VRM 皮套与全身动作映射。

## 看效果

Windows 双击 `Start-MotionLab.cmd`，或运行：

```powershell
uv sync --locked
uv run --locked python tools/fetch_avatar.py
uv run --locked python -m dollfight.server --open
```

打开 <http://127.0.0.1:18943/>。首次同步 Python 依赖、下载官方样例 VRM 需要网络；之后本机 CPU 算法与浏览器渲染均可离线运行。无需摄像头、训练服务器或 Unity。端口占用时加 `--port 18944`。

默认显示 **真人回旋踢骨架 → 动漫 VRM**。建议按以下顺序验收：

1. 点“1. 右回旋踢”，用 **0.25×**、暂停和步进看提膝、支撑脚枢转、转髋、躯干倾斜、伸腿与回收。默认不再演示程序拼接的旋转动作。
2. 切换“真人前踢”“下段格挡”“手刀防御”“真人拳击”。拳击有侧身、降低重心的观察段落；不要把片段标题当作识别标签。
3. 打开骨骼/网格；选择几何人偶后可做长臂、宽肩比例对照。VRM 使用导入模型自己的骨长，也支持导入本地内嵌资源的 `.vrm`。
4. 看下方两个玩家视窗：默认全身取景，保留拳脚和反应空间。“严格眼位实验”仍可开启，但需要物理屏幕尺寸、位置和眼位标定。
5. 切到“对战视图”检查距离、攻击窗口、格挡与碰撞。调整距离后重新计算；前摇无伤害，后摇不能马上再出招，前后摇被打有额外惩罚。

**真人动作的参考攻击时序与规则识别结果分别保存、显示。** 原始动捕不经过人为抬肢体再整体旋转；识别器不读取片段名称或参考标签。旧合成对练保留在下拉框中用于逻辑回归，不能作为动作质量的证据。

## 已实现与边界

| 部分 | 当前交付 |
| --- | --- |
| 骨架处理 | 米制坐标、相机适配、标定、置信度门限、One Euro、缺失预测、固定骨长、关节限位 |
| 全身映射 | 独立骨盆/胸腔朝向，保留躯干扭转；肘膝弯曲平面；按腿长缩放、接地与双骨 IK |
| 动作识别 | 基础拳/膝/踢/蹲/侧倾、回旋踢、转身、护架、拨挡与组合规则；提膝候选延迟，防止踢腿前摇误报膝击；踢腿配合摆臂不再算独立出拳 |
| 皮套 | three-vrm 3.5.5 实际加载官方样例，19 个映射关节；处理额外肩/胸节点与 bind pose；模型缺少必需映射时明确报错 |
| 交互验证 | 动捕/骨架/模型对照、逐帧、慢放、噪声消融、全身玩家视窗、实际影响伤害与出招的前后摇 |
| Unity 交接 | [UPM 包与导入步骤](unity/README.md)：UniVRM 加载、Humanoid 映射、坐标转换、全局旋转回放、自动创建检查场景 |

浏览器 VRM 路线已可运行。**本机没有 Unity Editor，Unity 包尚未完成 Editor 编译、导入与播放验收。** 不能把 Python/浏览器测试称为 Unity 验证。

仍未完成：Gemini 实机输入、实时双人同步、基于大量真人数据的分类器、自然的任意招式过渡/受击动画、正式角色资产和大招库。这里保留真人全身运动，而非肌肉/动力学仿真。位移放大和对战边界仍可能造成滑步；动作检查视图保留采集根位移，便于直接发现这一问题。P2 是延迟回放，不能当成实时对手。

## 验证与协作

```powershell
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python tools/check_contracts.py
node apps/motion-lab/tests/run-tests.js
```

Python 3.10.19、uv ≥0.9.17、依赖由 `uv.lock` 固定。Node 22+ 仅用于投影测试；启动界面不需要 npm。浏览器依赖、许可证和 SHA-256 在 `apps/motion-lab/vendor/`，公开动捕的原始哈希在每个样本内；VRM 用 [下载清单](data/avatars/sample.json) 固定，10.8 MB 文件保存在忽略目录。

- [当前实现、失败边界与验收方法](docs/motion-lab.md)
- [Unity 导入与回放交接](unity/README.md)
- [二次元皮套：Tripo / SkinTokens 路线、接入检查与实测记录](docs/avatar-pipeline.md)
- [Git 与 uv 协作规范](CONTRIBUTING.md)
- [跨组协议](docs/contracts.md)、[JSON Schema](src/dollfight/schemas/)、[协议样例](tests/fixtures/)
- [动捕来源与致谢](data/samples/README.md)

远端为 [PoesisQ/3DDollFight](https://github.com/PoesisQ/3DDollFight)，当前工作分支 `feat/motion-lab`。
