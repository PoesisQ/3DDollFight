# 3DDollFight

3D 视觉课程项目：双人 RGB-D 体感格斗。当前仓库聚焦 **三维骨架约束、角色重定向、动作识别与多视角渲染的技术设计和协作接口**。

已知条件：摄像头大概率为 Orbbec Gemini 系列；引擎尚未确定；优先节约本地算力，必要时可租服务器训练。此处不重新安排小组分工或演示日期。

## 从哪里开始

- [技术方案](docs/technical-design.md)：几何、骨架、招式、皮套、视角、实验和实现顺序。
- [渲染与 agent 选型](docs/engine-choice.md)：Unity、Godot、Three.js 的取舍。
- [跨组接口草案](docs/contracts.md)：坐标系、时间、关节、事件和资产交付规范。
- [Git 与 uv 协作](CONTRIBUTING.md)：分支、PR、二进制资产、依赖和复现实验。
- [协议 JSON Schema](src/dollfight/schemas/) 与 [合成样例](tests/fixtures/)：供各端提前对接。

## 已实现 / 尚未实现

已实现：uv 项目配置、Git/LFS 属性、Python 核心 CI 配置、协议校验、反投影与坐标变换函数及离线测试。样例是人工构造的协议数据，没有真实人体信息。

尚未实现：相机接入、实时人体检测、骨架优化、动作分类、网络回放服务、角色蒙皮和任何引擎场景。设计中的算法、性能指标和动作数量是后续目标，不能视为实测结果。

GitHub 远端：[PoesisQ/3DDollFight](https://github.com/PoesisQ/3DDollFight)。`origin` 指向此仓库；推送与 PR 会触发已配置的 CI，实际结果以 GitHub Actions 为准。

## 本地复现

Python 3.10.19 暂与已有课程 Lab3 保持一致；在接入视觉 SDK 前再统一评估升级，不能每个组员单独升级。uv 最低版本 0.9.17，CI 固定为本机已验证的 0.9.17。当前只安装 NumPy、协议校验和开发工具，不要求 CUDA 或摄像头。

```powershell
uv sync --locked
uv run --locked pytest -q
uv run --locked python tools/check_contracts.py
uv run --locked ruff check .
uv run --locked ruff format --check .
```

安装 Git LFS 后，每个克隆运行一次 `git lfs install --local`。项目缓存 `.uv-cache/` 和环境 `.venv/` 均不提交。

建议先实现的一条完整路径：**录制或合成的骨架序列 → 稳定骨架 → 一个标准绑定模型 → 一个可解释的直拳事件 → 同一场景的三个视角**。用这条路径验证协议，再扩展动作和皮套。
