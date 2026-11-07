# 战斗界面与打击反馈

## 街机美术升级（2026-11-06）

普通场地采用工业擂台：带法线的混凝土地面、金属结构、双色灯带和原创墙面标识。正面主光与角色补光增强人物层次，脚下柔和接触阴影随脚部离地高度衰减。教堂继续使用原 Gaussian Splat 扫描，单独保留适配教堂的灯光与取景。

HUD 使用粉红 P1 / 冰蓝 P2、斜切生命条、扣血残影、六段防守槽与中央倒计时。左右位置由主镜头中两名角色的骨盆投影确定：普通场地 P1 在左，教堂反向取景时 P2 在左。名字、头像、血量、防守、胜场、接触提示及玩家观察窗共用稳定的侧别映射，动作短暂交叉和时间轴跳转不会使血条闪换；镜头反向时刷新。玩家编号、配色和赢家仍对应真实阵营。

六段槽显示原有 `guardEnergy`，没有增加新的必杀或 Drive 规则。头像由现有角色在启动时各渲染一次，主循环不增加头像相机。开场 READY / FIGHT 与 KO 使用动态排版；KO 演出后显示真实胜者和可点击的“再战一局”。中文设置保留所有排练工具并按窗口高度缩放。

接触效果由真实事件驱动，命中使用玩家色斩线、亮核和飞屑；格挡、拨挡、破防分别采用蓝、薄荷、金色。接触点保留小伤害数字，招式和连击移到两侧。五个 Kenney 短音效叠加程序低音层，声音与屏幕反馈仍由同一个事件消费者触发。

新增外部素材均随项目本地加载，原件合计约 0.8 MB。来源、许可和 SHA-256 分别保存在 [字体清单](../unity/Assets/Resources/DollFight/Fonts/ATTRIBUTION.md)、[材质清单](../unity/Assets/Resources/DollFight/Textures/ATTRIBUTION.md)、[音效清单](../unity/Assets/Resources/DollFight/Audio/SOURCES.md)。字体来自 Google Fonts（OFL），混凝土来自 Poly Haven（CC0），接触音效来自 Kenney（CC0）。教堂扫描仍沿用其独立许可和署名。

下面的操作、时钟与结算规则继续适用。当前 showcase 原生验收记录保存在 `outputs/showcase-review/`；`outputs/arcade-polish/` 和 `outputs/combat-polish/` 保留此前版本的历史证据。

## 取景与规则

Unity 的普通场地与 Saint Maurice 教堂共用本轮呈现。默认使用单个 16:9 主画面；窗口改变比例时等比取景并留边，双方玩家观察窗由 **V** 开关。独立程序默认窗口为 1440×900。

默认 showcase 以 **1.2 倍源速率**播放，`regulationDuration = 66` 源秒对应 **55 秒常规倒计时**。`presentationRate` 与 `regulationDuration` 由导出时间轴提供，HUD 用同一速率换算显示时间；设置中的 1× 表示该展示的默认节奏。旧数据未提供速率时仍兼容原播放方式。

当前导出素材总长 56.3667 源秒，在 54.7 源秒、即显示时间 **45.5833 秒**由真实命中产生 KO，P1 获胜，最终 HP 为 **51 / 0**。全局 10 次命中、10 次格挡、0 次挥空，双方分别有 7 / 3 次命中，没有 recovery 拒绝或取消的攻击。实际造成伤害的五类招式为直拳、前踢、侧踹、回旋踢和腾空旋踢，均来自既有 CMU 动捕。最终导出摘要见 `outputs/showcase-review/candidate-guard-final/summary.json`，原生自然播放耗时见下文复验记录。

双方生命值全程累计，不随动作段切换重置。只有一方生命归零才产生 KO 结果；同帧双方归零为双 KO。常规时限后尚未 KO 则进入加时，不按剩余血量判胜。命中停顿会增加少量墙钟时间，因此导出的源时间、HUD 显示时间和自然播放耗时分开记录。底层回放与 `Seek` 使用源时间，保证动作、接触与胜负同步。Motion Lab 的旧三回合排练继续保留。

## 操作

| 操作 | 按键 / 入口 |
| --- | --- |
| 暂停 / 继续 | Space、底部播放按钮 |
| 从头开始 | R、底部重新开始 |
| 双玩家观察窗 | V |
| 设置 | Esc、底部设置 |
| 音效开关 | M |
| 震屏开关 | N |
| 判定体 | B、设置中的排练工具 |
| 自身手脚 | H、排练工具 |
| 双方选角 | T / Esc，分别选择 P1/P2 后“应用角色并重开” |
| 慢放、音量、反馈强度、手柄震动 | 设置 |
| 时间轴、下一次交锋、跳至终局 | 设置 → 排练工具 |

顶部两侧显示真实生命值、扣血残影和防守槽；中央显示单局倒计时或加时。KO 后停止并展示真实胜负。主界面保留动捕排练标识。调试跳过会定位到下一次真实接触或终结一击之前再继续播放，不直接伪造伤害或胜负。

## 反馈与时钟

`export_duel` 将规则引擎已经结算的接触导出为 `contacts`；同帧双方命中各自保留，ID 带回合号。只对实际命中、格挡、拨挡和破防产生接触反馈，挥空不伪造命中。位置沿用标准碰撞体的坐标约定。

`DuelFeedback` 统一消费事件，驱动冲击斩线、飞屑、伤害字样、本地 Kenney 短音效与程序低音层、短暂命中停顿及衰减震屏。停顿作用于排练播放时钟，不修改 Unity 的全局 `Time.timeScale`。可选 XInput 震动在没有手柄时静默跳过。观察窗和 HUD 只读取结算，不重复消费事件。

暂停、失焦、跳转、重播、禁用和退出会清理残留反馈；短距离拖动同样重置事件消费记录。观察窗数量不影响音效和命中的触发次数。录像使用墙钟生成帧索引，以保留命中停顿。

## 复验

重新导出数据后构建两个场景，已有 EXE 不会自动读取修改后的 C# 或回放：

```powershell
uv run --locked python tools/prepare_unity.py
unity test unity --mode EditMode
# Unity 菜单 DollFight → Build Windows Demo
# Unity 菜单 DollFight → Saint Maurice → Build Church Duel
```

运行时参数 `-dollfightPresentationReview <绝对目录>` 自动保存常规窗口、较窄窗口、观察窗、设置、真实接触与结算截图；加 `-dollfightReviewQuit` 可在完成后退出。命中截图保持播放状态；暂停清理后的静态图不能用于判断命中特效。

新版截图还覆盖 READY / FIGHT、1920×900 宽窗口和 KO 演出后的稳定胜负页。验收播放器须以可见窗口启动，Windows 隐藏窗口启动可能在第一次调整大小前返回黑色截图。运行时基准可加 `-dollfightBenchmark <绝对JSON路径> -dollfightBenchmarkSeconds 15 -dollfightBenchmarkViews 1 -dollfightReviewQuit`，测量默认单视角；省略时长和视角参数仍沿用旧的 90 秒三视角基准。

2026-11-06 showcase 验证：全量 Python **237 项通过、1 项跳过**，Unity EditMode **34 项通过**，浏览器 **14 项通过**，协议样例 **2 项通过**。最后两处同长度动作替换后，分别再次通过 5 项 showcase 专项和 Ruff 检查。普通场地与教堂两份程序的时间轴、双方动作和来源记录均与源导出的 SHA-256 一致，记录在 `outputs/showcase-review/packaged-assets.json`。

终版普通场地原生几何复核覆盖全部 20 次接触，采集 138 个实际世界骨骼姿态；在事件前后约 0.1 源秒窗口内，10 次伤害均有身体代理重叠，10 次格挡均有对应防守侧前臂重叠，整窗口无接触的异常事件为 0。方法和逐事件数值见 `outputs/showcase-review/verified-native-analysis.md`。该结果基于骨骼及既定碰撞半径；少数事件的原生重叠比结算时刻晚数十毫秒，不代表蒙皮三角形或每帧特效相位完全对齐。

教堂 Direct3D 12 独立程序完成终版自然连播：**46.647 秒墙钟到达真实 KO，48.015 秒显示稳定胜负页，整段记录 48.063 秒**，包含命中停顿和结果演出，完整展示低于一分钟。记录中的 `interrupted=false`、最终接触 `r1-combat-20`、P1 获胜与 HP 51 / 0 均与导出一致。证据为 `outputs/showcase-review/church-verified-match/complete.json`、同目录 `result-settled.png`，以及 `outputs/showcase-review/church-verified-match.log` 的完成标记；已检查终局截图中教堂左侧为 P2、右侧为 P1。

普通场地独立程序同样完成终版自然连播：**46.632 秒墙钟到达真实 KO，47.990 秒显示稳定胜负页，整段记录 48.014 秒**。`outputs/showcase-review/studio-verified-match/complete.json` 确认未中断、最终 HP 51 / 0，终局截图中的重赛文字和完整工具栏正常。两个场景含结果展示的实测耗时均低于一分钟。

布局与设置截图分别保存在 `outputs/showcase-review/studio-final/` 和 `outputs/showcase-review/church-presentation/`，覆盖 1440×900、960×640、1920×900、玩家观察窗和排练工具。两份摘要的主画面比例均为 1.777778。普通场地终版结果使用 `studio-verified-match/result-settled.png`，教堂终版结果使用上述 `church-verified-match/result-settled.png`。自动跳转审查中的普通场地结果单帧曾缺少部分文字，最终 UI 以自然连播截图为准；前一轮教堂目录里的旧结果图保留历史。

正常启动使用 `Play-DollFight-Unity.cmd` 或 `Play-SaintMaurice.cmd`，不带自动跳转验收参数。

### 历史验证：旧三分钟版本

2026-11-06 较早版本本机验证：Python 232 项通过、1 项跳过，Unity EditMode 23 项通过，浏览器回归 14 项通过。普通场地与教堂的 Windows 程序均已重新构建，1440×900 和 960×640 窗口中的主画面都保持 16:9；两版接触、设置与 KO 截图保存在 `outputs/combat-polish/studio-final/` 和 `outputs/combat-polish/church-final/`。

当时的教堂版本还完成一次不中途跳转的自然连播：实际耗时 193.203 秒，比赛显示时间 192.6667 秒。3:00 时双方生命为 37 / 5，继续加时，最后在 3:12.7 以 21 / 0 结束；墙钟差值包含命中停顿。记录见 `outputs/combat-polish/full-match/complete.json`。它是旧慢放版本的历史证据，不是当前 showcase 的耗时。

本轮改动集中于现有动捕排练的呈现与反馈，不新增实时相机输入或任意动作受击动画。
