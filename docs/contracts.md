# 跨组接口约定 0.1.0

状态：供采集、骨架、动作、渲染与战斗模块讨论的草案。当前机器可校验 PoseFrame 与 ActionEvent；AvatarPose、MatchState、标定文件和网络服务尚未实现，不能将本文当成已有完整协议栈。

## 数据边界

| 接口 | 生产 → 消费 | 必须携带的信息 | 当前状态 |
|---|---|---|---|
| CaptureFrame | 相机模块 → 姿态模块 | RGB/depth、各自时间、内参、畸变、对齐方式、depth scale、设备/固件/模式 | 设计 |
| PoseFrame | 观测适配 → 骨架求解/记录 | canonical19、三维位置、置信度、缺失状态、坐标与标定 ID | JSON Schema + 合成 fixture |
| AvatarPose | 重定向 → 引擎适配 | rig_id、root transform、局部骨旋转、序号、数据有效期 | 设计 |
| ActionEvent | 识别 → 战斗状态机 | 唯一事件、原语、侧别、高度、起止时刻、置信度、源帧 | JSON Schema + 合成 fixture |
| MatchState | 权威战斗端 → 所有视图 | tick、角色位置朝向、血量、动画阶段、已确认事件 | 设计 |
| RigProfile | 资产制作 → 重定向/渲染 | 层级、语义映射、绑定变换、限位、模型单位、资源版本 | 设计 |

组件依赖接口和样例文件，而不 import 别的组私有脚本。识别事件是候选输入，是否允许出招、是否命中、扣多少血由战斗端决定；同一事件重复传输不能重复生效。

## 坐标和单位

所有位置使用米。相机原始毫米必须在采集适配层转成米。角度用于配置时明确 radians/degrees；骨旋转对外拟采用归一化四元数 `[x,y,z,w]`，不传含义不明的欧拉角。

| 空间 | 约定 | 用途 |
|---|---|---|
| camera_optical_rh | 右手；+X 图像向右、+Y 图像向下、+Z 光轴向前 | 当前 PoseFrame 唯一允许的坐标空间 |
| stage_rh | 右手；+Y 向上，固定舞台基准；约定 +Z 朝主屏参考观察侧 | 统一算法与角色状态；每路相机需各自外参/虚拟站位映射 |
| body_rh | 右手；+X 解剖右侧、+Y 躯干向上、+Z 向后；身体前方是 -Z | 去掉身高、站位和面对方向的识别特征 |
| Unity basis | 对舞台坐标执行 H=diag(1,1,-1) | Unity 适配器唯一执行此手性转换 |

`p_target = R_target_from_source p_source + t_target_from_source`，齐次矩阵按列向量定义；禁止用名为 `extrinsic` 却不说明方向的字段。当前 geometry 函数用 NumPy 行数组存点，但 API 语义仍是上述列向量变换。

Unity 中 `p_u=H p_s`，旋转操作 `R_u=H R_s H^-1`。H 的行列式为 -1，不能直接当作一个旋转四元数。示例 `diag(1,-1,-1)` 是合法 180° 旋转，但不能替代实测的相机外参。Godot/浏览器也要明确定义适配，不能凭“都是右手系”假设前向、模型绑定轴和相机 view convention 完全相同。

两个独立站位可各自定义从物理空间到虚拟舞台的映射，并不要求相机共同看见同一标定板。若要进行真实多视角融合，则必须额外标定共同物理坐标、时间同步和身份对应。屏幕视锥还需要相机/眼位与屏幕平面的关系。

## canonical19 与跟踪质量

以下名称集合固定；JSON 对象顺序不具备语义，消费端按名称读取。

```text
pelvis → spine → chest → neck → head
chest → left_shoulder → left_elbow → left_wrist
chest → right_shoulder → right_elbow → right_wrist
pelvis → left_hip → left_knee → left_ankle → left_toe
pelvis → right_hip → right_knee → right_ankle → right_toe
```

这是一棵观测/求解用的语义树，不是最终角色必须采用的全部绑定骨骼。头、颈、脊柱的中心定义及其构造偏移要写入标定/映射版本；不能把 MediaPipe 鼻尖直接更名为 head 中心。手指、脚跟、眼位和头朝向先保存在检测器原始记录中，后续通过新版本扩展，不能偷偷塞进固定 19 点字典。

每个 joint 有 `position_m`、`confidence ∈ [0,1]` 和 `tracking_state`：

- observed：来自当前帧有效传感器/图像证据的代理关节估计，仍不宣称解剖真值。
- inferred：通过单目先验、几何关系或骨架约束推断。
- predicted：依赖过去帧的短时预测。
- missing：位置必须 null，confidence 必须 0；不能用 `[0,0,0]`、NaN 或无穷值冒充缺失。

fixture 中的 confidence=1 是人工输入，不能作为 detector 校准结果。不同来源的 confidence 含义也不自动一致；应保留原始可见性/深度质量，并在适配器中定义融合质量分数。稳定的 player_id 来自站位/会话绑定，不等于检测器临时 body_id；身份重新匹配前禁发动作。

## 时间、序号与事件

`session_id` 区分一次采集/比赛；`stream_id` 区分一次连续采集进程。进程重启、相机切换或序号即将溢出时使用新 stream_id。PoseFrame sequence 从 0 递增，消费端按 `(session_id, stream_id, player_id)` 识别流，并拒绝旧帧/重复帧。

`captured_at_ns` 是该时钟域中的单调时间，优先由硬件时钟映射到明确的主机单调时钟。记录硬件到主机映射方法、同步误差与帧曝光语义。不是可直接比较的 UTC 日期。

纳秒时间戳在 JSON 内用十进制字符串，避免 JavaScript Number 的整数精度损失；计算时转换成 BigInt/足够宽的整数。`clock_domain` 明确时间属于哪个进程/设备映射域。不同机器的单调时间不能直接相减；需要交换时钟样本估计偏差/漂移并记录误差，跨机性能测量还可用统一外部视频。新版本不能把这些字段悄悄改成毫秒。

ActionEvent 包含 `event_id`、`action_id`、`side`、`level`、`started_at_ns`、`committed_at_ns`、`source_sequence`。动作起点不能晚于提交点，计时采用同一个 clock_domain。服务端按 `(session_id, stream_id, player_id, event_id)` 去重，按游戏 tick 接受/拒绝；客户端播放只依据确认后的状态。

`action_id` 语法已校验，但动作目录及允许的 side/level 组合还需随招式表冻结；当前校验器不会证明某个 action_id 实际存在。fixture 的动作帧与骨架帧仅演示单消息格式，不构成完整同步回放。

## AvatarPose 与资产交付建议

AvatarPose 应有 rig_id、绑定版本、root 的舞台变换，以及各 bone 的父节点局部旋转；“相对 rest 的增量”与“包含 rest 的最终局部旋转”必须二选一写进协议。建议输出 **包含绑定朝向的最终局部旋转**，骨局部平移默认用目标角色绑定值，不随人体检测逐帧缩放。不得把不同角色的骨名数组直接互换。

RigProfile 固定骨顺序、父索引、bind-local 矩阵、mesh transform、语义映射、twist 规则、限位和左右手。验收姿势至少包含 T/A-pose、手臂前伸、肘 90°、下蹲、抬膝和身体转向。Unity 优先 FBX 的常规导入路径；GLB 用于 Godot/浏览器，Unity 若选 GLB 需明确并锁定导入包。

每个资源记录：来源、允许的使用方式、文件 hash、作者/版本、导出工具与设置。皮套更换不应修改动作原语名称；招式片段同时标注前摇、有效期、恢复期、根运动与碰撞配置。

## 传输与录制建议

第一版可用本机/局域网 WebSocket + JSON，便于 Python、Unity、Godot 和浏览器对接。姿态与可靠事件用独立连接/队列：姿态仅保留最新值并限制积压；事件需确认、重发与幂等处理。WebSocket 自身的有序传输并不等于应用层无积压。不要在同一消息通道传大体积 RGB-D。

只有实测证明需要时再为姿态使用二进制或 UDP；不能将超过路径 MTU 的大 JSON 直接塞进单个 UDP 包而假设稳定。多人跨机下先记录接收/处理/显示时间和丢包，再做优化。

小型合成 JSON fixture 入 Git。真实录制采用本地/共享存储：RGB 与 depth 用合适的帧/视频格式，姿态 JSONL 或 NPZ；session manifest 记录版本、相机、标定、单位、时钟、文件 hash 和标签。不得把大量 RGB-D 或真人面部视频塞进普通 Git 历史。对外共享数据前按实际参与者授权范围处理。

ReplaySource 应替代 LiveSource 实现相同接口，并可选择原速、逐帧、固定步长、模拟丢帧。当前仓库只有消息 fixture，ReplaySource 未实现。

## 变更规则与接入验收

0.1.0 为严格草案 schema，接收器拒绝未知字段/版本；后续兼容行为必须明确升级，不能一面要求严格字段、一面宣称任意增字段天然兼容。修改单位、轴向、关节定义和时间语义都属于破坏性变化。

每次接口 PR 同时给出生产与消费两端的适配、小 fixture、迁移说明和已运行的检查。接入时按顺序验证：左右手、米/毫米、基变换、缺失、乱序/重复、身份重置、断流恢复，最后才检验完整对打画面。
