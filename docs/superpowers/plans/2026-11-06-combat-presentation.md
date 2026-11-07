# 战斗呈现与反馈打磨

**Goal:** 在现有 Unity 排练与教堂场景上完成可直接运行的游戏界面、正常取景和与真实接触同步的打击反馈。

**Architecture:** 保留 Python 结算和 Humanoid 动作数据；额外导出有唯一 ID 的接触事件。Unity 的 HUD/layout、反馈播放器各自独立，由 DollFightDemo 的同一播放时钟驱动。只修改本次涉及的文件，在当前未提交工作上增量完成。

**Tech Stack:** Unity 6000.3.27f1 / Built-in / IMGUI / procedural PCM / Python export。

## 当前验收要求

用户进一步要求：动作放慢、正式战斗采用 3 分钟常规倒计时，只有 HP 归零才结束，调试保留跳过。当前实现以此为准：Unity 默认单局 KO 模式，源时钟速率 0.75；常规期限为 135 源秒 / 180 显示秒，时间到未 KO 进入加时。生命与防守状态跨原编排段持续，不再按 30 秒分段回血或按剩余血量结算。Python 保留旧回合模式作为明确的兼容选项，Unity 准备脚本选择 KO 模式。调试入口提供下一次接触与终局跳转，正常工具栏收起时间轴。

## 视觉与交互

深墨色底、暖白文字、P1 青色/P2 暖红色识别。主画面采用适配窗口的 16:9 viewport，不对画面作非等比缩放；健康条和时钟在画面顶端，精简播放操作在底部。玩家观察窗为可开关的 16:9 小窗，默认关闭。设置收起判定体、角色切换、自身手脚、速度和反馈强度。保留排练模式标识。

命中瞬间显示局部冲击环、火花、伤害与连击提示，短暂冻结播放时钟并衰减震屏；格挡、拨挡和破防使用不同声音/颜色/强度。音效与震动均可关闭。暂停、跳转、失焦、重播和切换角色清除残留反馈；不修改伤害规则。

## 稳定接口

- Python timeline 新增 `contacts` 数组，每个元素为 `id, time, round, attacker, defender, action, outcome, label, damage, comboCount, counter, position`，position 使用现有 vector 坐标转换。
- 新建 `DuelContact` 数据类及 `DuelFeedback : MonoBehaviour`。公开 `Initialize(Camera camera, Shader shader)`, `ResetAt(float time, DuelContact[] contacts)`, `Advance(float previousTime, float currentTime, DuelContact[] contacts, bool playing)`, `float PlaybackDelta(float delta)`, `ApplyCamera(Camera camera)`, `DrawOverlay(Rect arenaPixels)`；`soundEnabled`, `shakeEnabled`, `hapticsEnabled` 设置；`LastContact`, `ContactAge` 只读状态。`ApplyCamera` 在布局设置/恢复基准相机后执行，不积累偏移；`Advance` 只消费前进区间，缺帧处理全部接触。
- `DollFightDemo` 增加 timeline contacts 字段，暴露 HUD 所需只读状态与播放操作。`Seek` 必须重置反馈，即使短距离拖动；正常更新先恢复上一帧相机震动，再设置相机，最后叠加当前反馈。

## 实施与验收

- [x] 导出结构化真实碰撞，验证双向同帧接触、稳定 ID、位置坐标和排序，运行 export 回归。
- [x] 实现独立反馈模块，生成一次性音频资源，事件去重、暂停清理、相机震动恢复和手柄停止；测试时钟与事件消费的实际边界。
- [x] 实现 HUD 和布局，接入 Demo，两个场景默认单主视图；更新启动窗口尺寸，保留既有角色与场景资源。
- [x] 加入三分钟单局 KO、跨编排持续血量、加时与真实终局跳转；验证计时与结束条件。
- [x] 生成新回放；Unity 实际编译、EditMode 检查、重新构建普通与教堂入口。
- [x] 原生运行截图检查 16:9、较窄窗口、玩家小窗和实际命中帧；查看异常日志，必要时修正。
- [x] 文档记录实际结果与操作方式，删除本轮无用临时文件。

验收结果：Python 232 passed / 1 skipped，Unity EditMode 23 passed，浏览器 14 passed；两个 Windows 构建成功。自然连播无中途跳转，193.203 秒墙钟后实际 KO，显示 3:12.7、最终生命 21 / 0。最终截图、日志与完整播放记录保留在 `outputs/combat-polish/`，操作和复验说明见 `docs/combat-presentation.md`。

用户已要求自主推进到完成；不增加设计审批停顿，不提交或覆盖既有未提交工作。
