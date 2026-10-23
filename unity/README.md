# Unity Humanoid 交接

此目录是可导入的 UPM 包，不是假装已经建立并验收的 Unity 工程。**本机没有 Unity Editor，尚未执行 Editor 编译、VRM 导入和场景播放检查。** Python 导出与坐标/FK数值测试不能代替这些验收。

## 接入步骤

1. 新建 **Unity 2022.3 LTS、Built-in Render Pipeline** 项目。引擎尚未由团队确定；这是最小验证目标，不强迫最终项目使用此版本。
2. 将 `manifest.fragment.json` 中两条 UniVRM Git 依赖合并进工程的 `Packages/manifest.json`。使用官方固定版本 v0.128.0。不要直接覆盖团队现有 manifest。
3. Package Manager → Add package from disk，选择本目录 `Packages/com.dollfight.humanoid/package.json`。或使用正确的相对 `file:` 路径；fragment 中本地路径仅是示例。
4. 在 Motion Lab 选择官方 VRM/真人动作，点击“导出 Unity 动作”。准备同一个 VRM 文件（仓库 `data/raw/avatars/sample.vrm`）。
5. Unity 菜单 **DollFight → Create VRM Replay Scene**，选择 VRM 与导出的 JSON，保存场景后 Play。Inspector 显示绑定状态，可关闭 playing 并逐秒修改 time，speed 可慢放。
6. Editor Test Runner 运行 `DollFight.Humanoid.Tests`；人工观察支撑脚、左右手、髋肩扭转、转身、面向与根位移。确认 Console 无错后，才能记录“Unity 验收通过”。

## 适配器做什么

`HumanoidReplay` 使用官方 `Vrm10.LoadPathAsync`，也可绑定已有 Animator。要求有效 Humanoid Avatar 和 19 个对应关节；缺少骨骼直接报出名称，不依赖场景对象同名查找。

从导入 T-pose 捕获每个骨骼的 bind 世界旋转，按 canonical19 顺序应用全局 delta，再乘模型 bind 旋转。额外肩/上胸层级由实际 Transform 父链处理。坐标采用 `H = diag(1,1,-1)`，四元数转换为 `(-x,-y,z,w)`，根位置转换为 `(x,y,-z)`。不要重复转换一次。

该回放组件接管骨骼，关闭 Animator 和 UniVRM 实例的自动更新，以免控制骨架覆盖姿态。没有驱动弹簧、表情、受击 Animator 或招式混合；这些将在引擎验证后接入。已有 Humanoid 必须处于导入 T-pose 后再绑定，不能用任意动作帧当 bind pose。

Python 输出已经按所选皮套求解。应优先用同一个模型验收；更换模型时要重新获取其 rest 骨架再求解，单独按身高缩放不能保证另一个体型也接地。

v0.6 的校服底模位于 `data/avatars/atelier/`。VRM 中保留人体、手指、扭转骨、MToon 和裙板 spring bone 链，可供引擎继续接入。但本包目前关闭 UniVRM 自动更新，未驱动 spring bones，也没有浏览器 `cloth.js` 的 PBD 求解或顶点缓存；因此不能把浏览器裙摆效果称为 Unity 已支持。后续需要在人体回放后显式更新次级骨骼，并移植裙布约束/碰撞，或由 Unity 服装系统实现同等效果后再验收。

## Git 与来源

包代码、asmdef 和 `.meta` 一起提交，移动文件保留 GUID。团队实际工程还需提交其 `ProjectSettings/ProjectVersion.txt` 和 `Packages/packages-lock.json`，不能用此包声明代替引擎版本锁。`Library/Temp` 不入库，正式 VRM/FBX 大资产走 LFS 或固定 manifest。

实现对照 [UniVRM v0.128.0 加载 API 源码](https://github.com/vrm-c/UniVRM/blob/v0.128.0/Assets/VRM10/Runtime/IO/Vrm10.cs)、[Unity Humanoid 配置说明](https://docs.unity3d.com/2022.3/Documentation/Manual/ConfiguringtheAvatar.html)。VRM 样例的模型许可与 UniVRM/three-vrm 的代码许可分别管理。
