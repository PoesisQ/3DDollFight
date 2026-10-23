# 3DDollFight

3D 视觉课程的双人体感格斗项目。当前已交付 **Motion Lab v0.2：可运行、可对照的骨架 → 动作 → 蒙皮 → 多视角原型**，重点实现我们负责的模块。

## 直接看效果

Windows 双击 **`Start-MotionLab.cmd`**（需已安装 uv），或在仓库目录执行：

```powershell
uv sync --locked
uv run --locked python -m dollfight.server --open
```

打开 <http://127.0.0.1:18943/>。Python 算法在本机 CPU 执行，Three.js 在浏览器 GPU 渲染；不需要摄像头、Unity、CUDA、训练服务器或 npm 安装。首次 `uv sync` 需要下载依赖；同步后回放不访问外网。服务仅监听本机，关闭终端即可停止。如果端口占用，用 `--port 18944 --open`。

建议先按这个顺序体验：

1. **招式巡检 → 骨架对比**：原始观测、约束骨架、目标蒙皮并排。暂停、逐帧、拖动时间轴；点击下面的事件回看出招前一瞬。
2. **目标角色比例 → 长臂 / 宽肩**：观察相同人体动作如何驱动不同骨长的角色。打开骨骼与蒙皮网格检查绑定。
3. **噪声 30 mm、缺失 15% → 重新计算**：对照关闭平滑、关闭骨长约束后的效果；预测/缺失关节会变色，不能作为出拳证据。
4. **CMU 14_01 真人拳击动捕**：看真实运动的自然度、脚滑和可疑事件。它是光学动捕，不是 Gemini 跟踪结果，没有逐拳标签。
5. **屏幕窗口透视 + 眼位偏移**：看两个玩家视窗的透视变化；关闭后可与普通 LookAt 对照。

详细说明、指标含义和当前不足见 [评估指南](docs/motion-lab.md)。

## 当前实现

| 层 | 可运行内容 |
| --- | --- |
| 输入 | 招式巡检、直拳、遮挡、转向、静止、24 秒真人动捕；PoseFrame JSONL 导入/导出 |
| 骨架 | canonical19、置信度/速度门限、One Euro 平滑、短时预测、固定骨长、肘膝限位 |
| 重定向 | 源体型标定、3 种目标比例、局部四元数、正向运动学、接地双骨 IK |
| 动作 | 左右直拳/勾拳/上勾拳/膝击/前踢、下蹲、左右闪避；局部坐标、体型归一化、回收再触发 |
| 渲染 | 层级骨架、加权 SkinnedMesh、可旋转主视图、两个对手视窗、off-axis 屏幕投影 |
| 评估 | 噪声/缺失注入、开关消融、逐帧状态、事件定位、报告导出、复现实验脚本 |

对战背景、皮套外观和扣血采用简化演示；P2 是错时回放。**尚未实现实机 Gemini 采集、真实双人联网、真实人物扫描皮套、细手指/前臂轴向旋转、正式连招与碰撞裁决。** 13 类在可控轨迹上的通过不等于真人识别准确率。当前路径先把我们的模块做成可检查的闭环，外部模块按协议替换输入即可。

## 验证与复现

```powershell
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python tools/check_contracts.py
node apps/motion-lab/tests/projection.test.js
uv run --locked python tools/evaluate.py
```

最后两条分别验证实际浏览器投影算法（需 Node 22+）和生成 `outputs/evaluation.json`。运行应用本身不需要 Node。Python 3.10.19、uv 最低 0.9.17；依赖由 `pyproject.toml` + `uv.lock` 管理。GitHub CI 覆盖 Windows/Linux 核心测试和投影测试。

Three.js 0.180.0 按官方 npm 包固定入库，附 MIT 许可证和文件哈希；不需要启动时访问 CDN。CMU 样本附 [来源、转换与致谢](data/samples/README.md)。原始大文件、个人录制和输出不进 Git。

## 协作入口

- [Git 与 uv 协作](CONTRIBUTING.md)：main + 短期 feature 分支、PR、LFS、复现要求。
- [接口草案](docs/contracts.md)、[JSON Schema](src/dollfight/schemas/) 和 [合成消息](tests/fixtures/)：给采集、游戏逻辑、引擎、美术组对接。
- [当前原型设计与验证](docs/motion-lab.md)：本次真正实现的算法、接口边界和评估方式。
- [整体技术方案](docs/technical-design.md)、[引擎与 agent 选型](docs/engine-choice.md)：后续路线讨论，不代表所有功能已落地。

远端：[PoesisQ/3DDollFight](https://github.com/PoesisQ/3DDollFight)。本原型位于 `feat/motion-lab` 分支；经 PR 检查后并入 main。
