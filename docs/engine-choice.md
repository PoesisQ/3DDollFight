# 引擎与编码 agent 的接入

状态：选型建议，未创建引擎工程。这里将“接入 agent”理解为编码 agent 能修改代码/场景、执行程序、检查日志/截图并复现问题。若未来需要游戏 AI 对手，它应走统一动作接口，是另一层问题。

## 建议

**首选 Python 算法服务 + Unity 渲染；若从零开始且更重视文本工程和自动化操作，则 Godot 是有力备选。** 算法、协议和回放保持独立，选择不应由某个第三方 MCP 插件是否存在决定。

这是结合本项目需求的工程判断，不是对所有游戏引擎的性能排名。

| 方案 | 本项目的优势 | agent 怎样工作 | 成本与限制 |
|---|---|---|---|
| Unity | Humanoid、Animator、IK、动画混合和多相机等现成功能适合角色格斗 | C#、Editor 脚本、batchmode、executeMethod、测试、确定性截图入口 | 场景 GUID、导入设置和编辑器环境要规范；正式运行测试需正确安装和许可条件 |
| Godot | 文本场景与脚本便于审查，命令行启动/导出方便；已有 humanoid 骨映射与重定向 | `.gd/.tscn/.tres`、CLI、测试场景、日志、固定帧截图 | 要自行落实运行时追踪到骨架的适配与部分动画工具链，需实测角色导入质量 |
| Three.js | 代码表达直接、浏览器运行和画面检查方便，适合骨架/坐标/回放调试器 | TypeScript、浏览器自动化、固定输入截图 | 骨骼蒙皮可用，但完整格斗状态、IK、角色工具及资产流程仍需较多工作 |

Unity 官方支持 [Humanoid 动画重定向](https://docs.unity3d.com/6000.0/Documentation/Manual/Retargeting.html) 和 [命令行编辑器执行](https://docs.unity3d.com/6000.0/Documentation/Manual/EditorCommandLineArguments.html)。Godot 官方提供 [SkeletonProfileHumanoid/BoneMap](https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/retargeting_3d_skeletons.html) 和 [命令行工作流](https://docs.godotengine.org/en/stable/tutorials/editor/command_line_tutorial.html)。浏览器路线可基于 [Three.js 的动画与蒙皮接口](https://threejs.org/docs/)。

Unreal 暂不作为首个验证目标：目前目标是轻量部署、清楚展示骨架算法与多人协作，先在上述方案中建立最小链路更合适；这不表示 Unreal 无法自动化或不支持重定向。

## 给 agent 建立明确入口

优先设计以下可脚本调用的能力，再考虑通过 MCP 包装。下面是拟定职责，当前未实现这些引擎命令：

- `build-demo`：从版本控制中的配置生成/验证测试场景，重复运行不产生重复对象。
- `play-recording <path>`：加载固定录制，使用固定种子与时间推进。
- `capture-frame <time> <camera>`：输出指定时刻、指定相机的 PNG，并输出对应骨架和矩阵。
- `validate-rig <asset>`：检查骨名、层级、绑定姿态、比例和权重。
- `report-metrics`：输出帧时、丢帧、丢关节、脚滑和事件信息。

Unity 场景由受版本控制的 C# 编辑器脚本或小 Prefab 生成；少让 agent 直接手改复杂 YAML/GUID。Godot 适合编辑文本场景，但同样需要引擎加载和画面验证。无图形 headless 检查能验证协议/逻辑，不能证明材质、蒙皮和渲染正确；视觉回归应另用具备图形上下文的测试入口。

让 agent 通过 **输入回放 → 执行 → 指标/截图 → 修改** 形成闭环，收益比“它能不能自动点击编辑器”更大。Unity/Godot 编辑器版本和插件版本也要锁定；uv 只管理 Python，不管理整个引擎。

## 最小比较试验

如确有选型分歧，可用同一个标准角色、同一个 pose 回放、同一个手臂 IK 目标和三个相机，在候选引擎中比较：导入是否正确、可否一条命令复现、修改后能否自动截图、CPU/GPU 帧时、Git diff 是否可理解。依据实际结果保留一个正式客户端，不长期维护三个完整游戏。
