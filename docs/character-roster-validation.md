# 新角色与选角验收（2026-11-07）

Unity 普通场地与 Saint Maurice 教堂默认使用 `tripo-b9e9ce29 / team`。两个 Windows 构建均已更新，入口仍为仓库根目录的 `Play-DollFight-Unity.cmd` 与 `Play-SaintMaurice.cmd`。

## 代码与资源检查

- Unity **51/51** 项检查通过。包含新 Prefab 的有效 Humanoid、19 骨、T-pose、米制比例与朝向、材质及 13 个真实动作采样的骨骼/蒙皮有限性。
- 真实场景重载验证了默认阵容、TRIPO 镜像、MIZORE / TRIPO 混合、恢复默认。每次只有一个演示实例与两个独立角色；旧 VRM 对象已销毁，四种阵容的 KO 快照均为 HP 51/0。
- 单槽独立选择、非法 ID、参数缺值/重复、旧 classic 入口、会话重载均通过。新录制边界检查确认距离 KO 不足 1 ms 时仍需继续，不能提前标记完成。
- Python **237 passed / 1 skipped**；Ruff 检查、格式检查、两份协议样例及 `git diff --check` 通过。准备脚本实际重新导出 1,692 组双人帧。
- 源 FBX 角色与 Unity 均为 **10,880 三角面**；源模型 5,614 顶点、67 骨，四张 4096×4096 原贴图保留。压缩包及各原件哈希记录在 `unity/Assets/Art/TripoB9E9/provenance.json`。
- `duel.json` 改造前后 SHA-256 均为 `a12945cca07c720428e4d3c28b7b9eee84caa5183b4b35d12c39c34e3a150401`。20 次接触、五类实际伤害招式、最终生命值与胜者未改变。

Unity XML 与构建日志保存在 `outputs/character-review/`。旧 VRM 的共享弹簧骨卸载路径曾产生两份 Persistent 分配告警；使用 UniVRM 的独立运行实例后，同一场景重载测试通过，最终退出日志不再出现该告警。

## 原生演示

| 检查 | 普通场地 | 教堂 |
| --- | --- | --- |
| 实际两槽 ID | tripo-b9e9ce29 / team | tripo-b9e9ce29 / team |
| 连续播放至稳定结算 | 47.986 s | 47.929 s |
| 真实终局 | finished，P1 获胜 | finished，P1 获胜 |
| 最终 HP | 51 / 0 | 51 / 0 |
| 最后一击 | r1-combat-20 | r1-combat-20 |
| 录制中断 | false | false |
| 视频 | 1440×900 / 30 fps / 48.000 s | 1440×900 / 30 fps / 47.933 s |
| 原生采集帧 / 重复帧 | 1440 / 0 | 1278 / 160 |

[普通场地完整录像](../outputs/character-review/studio-match/review.mp4) · [教堂完整录像](../outputs/character-review/church-match/review.mp4)

已检查原生截图和录像采样中的开场、移动、出拳/踢击、格挡与命中、HP、玩家观察窗、角色头像、名字及 KO。教堂相机反向时左右 HUD 与真实玩家身份一致。旧 `-dollfightClassic` 的两份 VRM 也完成原生截图验收，保留衣发更新、对应头像及相同终局。

`studio-presentation/`、`church-presentation/` 与 `classic-presentation/` 保存三种分辨率、设置/排练工具、接触、腾空旋踢与结算截图。选角菜单的排版由原生截图确认；换角执行通过真实场景集成测试确认。Windows 窗口抓取工具本次超时，因此不把鼠标点击当作已完成的验证证据。

## 未录制时的短时运行检查

本机为 **NVIDIA GeForce RTX 3060 Laptop GPU**，1440×900、默认单主视角，每场分别预热后测量 15 秒。测量时未同时录制，仍有正常桌面活动；这是本机短时运行数据。

| 场景 | 平均 FPS | 帧时间中位数 | P95 | 非有限骨骼帧 |
| --- | --- | --- | --- | --- |
| 普通场地 | 118.49 | 8.34 ms | 8.73 ms | 0 / 1778 |
| 教堂 | 62.65 | 15.84 ms | 16.89 ms | 0 / 940 |

原始数据为 `outputs/character-review/studio-performance.json` 和 `church-performance.json`。

## 实际边界

教堂完整录制、classic 截图和两个短时基准程序出现了自动退出清理阶段滞留。完整结果和录像已经写盘，随后按各自 PID 结束了本次测试进程；退出阶段的原因尚未定位。普通场地完整录制正常结束。这一自动退出行为不列为通过项。

视频采用真实实时采集，漏采时重复上一帧并计数，没有离线减速。教堂录像中开启了玩家观察窗；视频采集帧数不能作为未录制时的游戏 FPS。

新角色衣服与头发沿用原蒙皮，没有新增布料/发丝物理。战斗判定继续使用标准骨架；这些检查不等于任意姿势零穿模或按新服装外轮廓拟合判定体。
