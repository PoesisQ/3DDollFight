# Unity 角色目录与选择

默认对战为 **TRIPO / CHALLENGER**。TRIPO 来自用户提供的 `tripo_convert_b9e9ce29-c08e-4b8d-80aa-684acc71674c.zip`，替换原 P1 校服女孩；原 NOZOMI、MIZORE 保留在目录中。普通场地和教堂共用同一套选角与回放逻辑。

正常启动先进入独立的双人选角界面：P1 用 WASD / F，P2 用方向键，Tab 切换当前玩家，Enter 确认，也可用鼠标选卡；双方确认后选择场地并开始。双方可以选择同一角色；新对战同步刷新模型、头像、名字与胜者显示。对战中 **T** 返回选角，**Esc** 打开设置，设置中也有选角/场地入口；R 只重开当前阵容。选择保留到本次程序退出，重新启动使用默认阵容。完整操作见[街机选择说明](arcade-selection.md)。

## 配置与接口

角色目录位于 `unity/Assets/Resources/DollFight/Characters.json`。

| ID | 显示名 | 资源 |
| --- | --- | --- |
| `tripo-b9e9ce29` | TRIPO | `DollFight/Characters/TripoB9E9` Prefab |
| `team` | CHALLENGER | `TeamCharacter` Prefab |
| `nozomi` | NOZOMI | `nozomi.vrm` 与其布料配置 |
| `mizore` | MIZORE | `mizore.vrm` 与其布料配置 |

`CharacterCatalog` 负责资源配置与 ID 检查，`CharacterSelection` 负责两个独立玩家槽。正式选角界面通过 `DollFightDemo.StartMatch(playerOneId, playerTwoId, stageId)` 同时确认双方角色和场地：全部 ID 及场景可加载性通过检查后才提交选择，并重载所选场景直接进入战斗。保留 `SelectCharacters(playerOneId, playerTwoId)` 供既有工具应用双方选择并重载当前场景。`SelectedCharacter(0/1)`、`CharacterIds` 与 `SelectedStageId` 提供当前信息。

命令行可用 `-dollfightP1 <id> -dollfightP2 <id>` 指定初始阵容；`-dollfightClassic` 使用 NOZOMI / MIZORE，单槽参数可覆盖它。启动参数只解析一次，之后在界面选择的角色不会被旧启动参数覆盖。非法 ID、缺值或重复的单槽参数会明确报错。

动作文件为 `player-1-motion.json`、`player-2-motion.json`，由 `tools/prepare_unity.py` 导出；它们表示玩家槽位，不属于某一角色。命中、格挡、生命值和 KO 继续读取同一 `duel.json`。角色体型变化经过既有 Humanoid 映射、垂直比例与鞋底接地处理；战斗判定仍使用标准骨架，尚无按各角色服装外轮廓拟合的独立判定体。

新增角色时，准备有效 Humanoid、19 个映射关节与 T-pose 的 Prefab，或使用兼容的 VRM，然后向目录增加配置。`firstPersonShoulderOffset` 只影响自身视窗，x/y 分别为肩部向后/向下的米制偏移；当前只有 CHALLENGER 的大肩甲使用此修正。布料配置可选，不能把旧角色的裙子控制网格套在新模型上。

每个 VRM 使用 UniVRM 提供的 `Vrm10FastSpringboneRuntimeStandalone`，由当前角色逐帧更新并随角色销毁，避免共享弹簧骨服务跨场景延迟移除时留下原生备份数组。场景测试同时检查旧 VRM 对象已销毁，没有残留实例。

## 新模型导入

源角色有 **67 个蒙皮骨骼、5,614 个顶点、10,880 个三角面**。原 FBX 和四张 4096×4096 贴图保存在 `Assets/Art/TripoB9E9/`，SHA-256、源归档与通道转换记录见同目录 `provenance.json`。原件不降面、不缩图。Unity Standard 材质使用原颜色/法线，另将金属度 R 与 `1 - roughness` 合入 metallic/smoothness 贴图。

导入器显式映射原骨名及手指，校正略低的手臂为 T-pose，统一头骨高度到 1.48 m，并在保存 Prefab 前验证鞋底蒙皮权重。新模型的衣服与头发沿用其原蒙皮，未生成额外布料或发束模拟。

从原压缩包重新准备：

```powershell
uv run --locked --group assets python tools/prepare_tripo_character.py
# Unity 菜单：DollFight → Prepare Tripo B9E9 Character
# 或批处理：-executeMethod DollFight.Editor.TripoCharacterImport.Prepare
uv run --locked python tools/prepare_unity.py
```

新克隆已有版本化 Prefab/材质/模型，无须重复从外层压缩包导入；正常执行原启动流程准备回放即可。

## 回放与录制验收

双 FBX 能同步完成加载，因此播放时钟在首个完整渲染帧后建立，避免把加载耗时计入开场。录制还会先预热并归零，再开始计时。完整录制严格等待真实 KO 快照；不再用 2 ms 容差提前停止，防止视频缺少最后一击与结算。

自动录制、截图、基准或几何审计可附加 `-dollfightUnattendedReview`，让诊断在窗口失去焦点时继续播放并保留接触反馈。该选项仅搭配诊断命令生效，普通演示仍按原规则在失焦时暂停。

选角集成检查通过真实 Unity 场景重载执行默认阵容、TRIPO 镜像、MIZORE / TRIPO 混合及恢复默认，检查场景里只有当前两个独立角色，并核对同一 KO 快照。素材检查使用真实 Prefab、19 骨绑定、蒙皮采样及 13 个实际回放时刻。

完整录像、测试结果、实际性能与退出清理边界见[本次验收记录](character-roster-validation.md)。
