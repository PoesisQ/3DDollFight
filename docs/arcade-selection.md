# 街机选角、场地选择与云台

**仓库不含教堂 / Cloud 扫描及其预览图。** 新克隆先拉取 LFS、准备动作，使用地下竞技场；其余场地的 `.unity` 文件已保留，恢复前缺少扫描，菜单图片显示占位。[地图恢复说明](map-assets.md)列出每个转换产物的放置位置和校验方法。`outputs/` 不随克隆分发，以下 `Play-*` 入口均要求已有本机构建。

双击根目录 `Play-DollFight-Unity.cmd` 进入全屏选角界面，确认双方角色后选择场地，再开始对战。`Play-SaintMaurice.cmd` 使用同一流程，初始选中教堂；两种构建均包含地下竞技场、Saint Maurice 和 Cloud 三个场地，启动器使用 Direct3D 12。窗口默认 1440×900，可缩放。

两个启动器共用最新的 `outputs/arcade-select/DollFight.exe`。教堂入口通过 `-dollfightMenuStage saint-maurice` 设置选场页默认值，不跳过选角或立即载入对战。`DemoBuild.BuildWindows` 默认写入这一新目录；自动化构建可加 `-dollfightBuildOutput <exe绝对路径>` 输出到另一个目录，保留用户正在运行的程序。

## 操作

| 页面 | 操作 |
| --- | --- |
| 选角色 | P1 用 WASD 移动、F 确认；P2 用方向键移动。Tab 或鼠标点击玩家区切换当前玩家，Enter / Space 确认当前玩家；小键盘 Enter 直接确认 P2 |
| 鼠标选角 | 点击角色卡给当前玩家选择；分别确认 P1、P2 后进入场地页。双方可选同一角色 |
| 选场地 | A/D 或左右方向键切换，鼠标可点场地缩略图；Enter / Space 或“开始对战”确认 |
| 返回 | Esc / Backspace：场地页回到选角并保留候选；角色页先取消确认。首次启动留在选角；从已有对战返回时，可继续按返回恢复先前的播放/暂停状态 |
| 对战 | T 返回选角并暂停战斗；Esc 打开设置，设置内也有角色/场地入口。Space 暂停，R 重开当前阵容，V 切玩家窗，M/N 切音效/震屏 |

菜单打开时，回放时间、命中反馈和战斗 HUD 暂停。角色模型使用各自的原生 Humanoid 资源生成选角立绘；场地图来自实际 Unity 场景的相机渲染。确认新对战会重新载入所选场景并直接进入战斗。角色和场地选择只在本次程序内保留。

## 场地与构建

| ID | 场景 | 预览 Resources 路径 |
| --- | --- | --- |
| `underground` | `Assets/Scenes/DollFight.unity` | `DollFight/Selection/Stages/underground` |
| `saint-maurice` | `Assets/Scenes/SaintMauriceDuel.unity` | `DollFight/Selection/Stages/saint-maurice` |
| `cloud` | `Assets/Scenes/CloudDuel.unity` | `DollFight/Selection/Stages/cloud` |

`StageCatalog` 是场地白名单。`DollFightDemo.StartMatch(p1Id, p2Id, stageId)` 先验证双方角色、场地 ID 和场景可加载性，再提交选择并载入场景。保留 `SelectCharacters(p1Id, p2Id)` 供既有工具重载当前场地。新克隆先准备动作和本地扫描数据，再通过 Unity 菜单 **DollFight → Build Windows Demo** 构建；教堂的 **Build Church Duel** 同样打包三个场地。

如果取回的是已转换的 `church.spz` / `cloud.spz`，直接放回[清单](../data/environments/restore-manifest.json)对应位置，用 `Start-Unity.cmd` 打开工程即可使用已有场景；无需原始 SOG / PLY，也无需再次转换或 Create 场景。地图和预览图恢复后、规则或动作更新后，都需重新构建才能更新 `outputs/` 中的独立程序。

## Cloud 原始数据与平台标定

第三场景使用用户提供的 `cloud.ply`，默认位于仓库的上一级目录。准备脚本验证原件 SHA-256、PLY 字段和全部 **594,371 个 SH0 splats**，通过固定版本 `@playcanvas/splat-transform 3.10.3` 转为 SPZ v4，保留全部有效点。原文件不被覆盖；本地输出位于 `unity/Assets/StreamingAssets/Environments/Cloud/`，包含 `cloud.spz` 和 `provenance.json`。原扫描、转换产物与原生场地图按现有本地扫描素材规则管理。

```powershell
uv run --locked python tools/prepare_unity.py
uv run --locked python tools/prepare_cloud.py --source ..\cloud.ply
# 源文件和配置未变时复用已验证缓存；强制重新转换可追加 --force
# 仅需重新生成场景时：DollFight → Cloud → Create Cloud Duel
# 批处理入口：-executeMethod DollFight.Environments.Editor.CloudScene.CreateDuel
# 然后：DollFight → Build Windows Demo
```

需要 Node.js 22+；脚本会在本地缺少转换器时用 `npm ci` 安装固定依赖。教堂数据的准备和来源仍见[教堂场景说明](saint-maurice-scene.md)。

标定参数记录在 `data/environments/cloud.json`。支撑面取较大的金色刻纹圆台顶面，原坐标原点为 `(1.6, -2.3, -0.49210526)`，拟合法线约为 `(0.02653103, -0.05914176, 0.99789697)`。Unity 侧反射源 Y、把源 Z 轴朝上映射为 Unity Y 轴，再消除顶面倾斜，仅把环境缩放 1.75 倍，并把该原点移到世界 Y=0。角色骨架、米制位移和动作时钟保持原有契约。

不可见的平台碰撞盒大小为 `(3.2, 0.2, 2.6)`，顶面 Y=0，位于测量的 2.1 m 安全内半径内。脚本检查两路完整源动作的脚/脚趾轨迹，并加入 0.30 m 鞋体余量；浮雕表面的实际高度分布单独记录。`outputs/cloud/grounding.json` 保存扫描与源动作的校验结果。重定向后的实际鞋底通过原生截图和蒙皮采样检查。

## 开发直达与快速复验

启动器透传附加参数。正常展示从选角开始；开发可以直接进入默认阵容或指定云台：

```powershell
.\Play-DollFight-Unity.cmd -dollfightSkipSelection
.\Play-DollFight-Unity.cmd -dollfightStage cloud
.\Play-DollFight-Unity.cmd -dollfightStage cloud -dollfightP1 tripo-b9e9ce29 -dollfightP2 team
```

角色参数和 `-dollfightStage` 只在当前会话首次解析，之后的菜单选择不会被旧参数覆盖。已有录像、截图、基准和几何审计入口会直接进入其诊断流程。对战设置中的“下一次命中”“跳至终局”和时间轴拖动可快速查看动作与真实终结一击，无须重新播放完整一局。

```powershell
# 单张实际场地图片，无人物、接触阴影和战斗 HUD；依次替换三个 stage ID
.\Play-DollFight-Unity.cmd -dollfightStage cloud -dollfightStagePreview "$PWD\outputs\selection-review\stage-cloud-native.png" -dollfightUnattendedReview -dollfightReviewQuit

# 菜单选择、镜像、三个场地页、紧凑窗口、切入 Cloud 后定点动作和真实终结一击
.\Play-DollFight-Unity.cmd -dollfightSelectionReview "$PWD\outputs\selection-review\native" -dollfightUnattendedReview -dollfightReviewQuit
```

场地图片生成后复制到表中对应的 `unity/Assets/Resources/.../*.png`，再重新构建。贴图采用 sRGB、无 mipmaps、bilinear、clamp、最大 2048 像素。快速复验输出 `selection-grounding-report.txt`，逐脚记录由脚/脚趾蒙皮权重筛选的实际最低鞋底、脚骨高度、碰撞面高度和间距；抬脚、踢腿、腾空时的正间距应结合动作与截图判断。`selection-complete.txt` 表示流程到达真实 KO；原生视觉和接地结论需结合截图审阅。

## 本次验证范围

2026-11-07 已通过 **22/22 项定向 Unity 测试**（`SelectionFlowTests`、`CharacterSelectionTests`），结果见 [`selection-tests.xml`](../outputs/selection-review/selection-tests.xml)。三个场地完成原生加载和空场地图捕获；Cloud 准备脚本与相关 Ruff 检查通过。新的三场地构建输出到 `outputs/arcade-select/`，构建进程正常退出。

快速原生流程完成默认/改选/镜像、三个场地页、960×640 窗口、场地返回角色页及确认 Cloud 后直接对战；没有重放完整一局。Cloud HUD 显示正确场地名，源时间 54.7 秒通过真实接触 `r1-combat-20` 结束，最终 HP **51 / 0**。截图和明确采用手工世界空间蒙皮的报告保存在 [`native-final`](../outputs/selection-review/native-final/selection-grounding-report.txt)；较早 `native` 目录中的旧截图和旧蒙皮采样已在仓库清理时移除。

在源时间 2、13.7、13.78333 和 54.7 秒共检查 **16 只脚**，从每只实际最低鞋底向下的射线均命中测量平台碰撞盒。2 秒姿态中，P1 支撑鞋底约低于碰撞面 0.25 mm，P2 两脚约为 +0.16 / −0.16 mm；P1 另一只抬脚约高 46.5 mm。动作采样的 P1 支撑鞋底间距约 14–24 mm、终结动作约 30 mm，P2 支撑鞋底约 1.3–2.4 mm；踢起的脚保留真实高度。全部源脚/脚趾轨迹在加入鞋体余量后，距安全圆台边缘的最小径向余量为 **0.708 m**。这组定点记录对应实际扫描平台、现用 TRIPO / CHALLENGER 和当前动作导出。

上述菜单验证使用原生公开接口与截图。用户停止桌面控制后未继续进行鼠标/键盘自动操作，因此不将其写作完整人工输入验收。
