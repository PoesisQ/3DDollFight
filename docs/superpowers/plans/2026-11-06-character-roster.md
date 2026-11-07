# Character roster and Tripo replacement

**Goal:** 默认 Unity 演示以素材 `tripo_convert_b9e9ce29-c08e-4b8d-80aa-684acc71674c` 替换 P1 校服女孩，双方角色经统一目录选择，保留原有单局 KO 内容。

**Architecture:** `CharacterCatalog` 从 Resources JSON 读取稳定角色 ID、显示名、VRM/Prefab 来源、可选布料及第一人称修正参数。`CharacterSelection` 保存两槽选择；模型加载、HUD、胜者与审计均读取同一配置。玩家动作文件属于 P1/P2，与角色 ID 解耦。设置提供简易双方选择及应用重开入口，为正式选角页复用公开选择接口。

**Tech Stack:** Unity 6000.3.27f1 / C# / UniVRM / Python staging.

## Tasks

- [x] 导入新 FBX：保留原网格和贴图，记录原 zip/资产 SHA-256，准备有效 Humanoid 与 T-pose 的 `Resources/DollFight/Characters/TripoB9E9.prefab`；验证全部 19 骨及朝向、比例、材质。
- [x] 建立角色目录与两槽选择：默认 `tripo-b9e9ce29` / `team`，旧 `nozomi` / `mizore` 可选；拒绝非法 ID，允许镜像对战；保留 `-dollfightClassic`，增加 P1/P2 启动参数。
- [x] 接入演示与 HUD：删除 `chosenTeam`/固定名字分支，双方可独立选择，应用后重载当前场景；头像、胜者、状态与测量标签随选择变化。肩甲修正仅用于 team。
- [x] 动作出口改为 `player-1-motion.json` / `player-2-motion.json`，两槽继续使用同一导出战斗时间轴。
- [x] Unity EditMode 覆盖真实 Prefab、目录完整性、独立槽位/错误 ID/镜像/旧入口；先观察新模型缺失断言失败，再导入验证。Python 现有导出和战斗回归检查。
- [x] 重新构建普通与教堂演示；原生定点截图、完整自然播放到 KO、玩家视窗及选择后的回放验收。默认单视角独立短时基准检查骨骼有限性与性能。截图检查新角色外观、动作、头像和结算名。
- [x] 更新 README、角色扩展说明和本次验证报告；保留原有未提交工作，不提交或回滚无关变动；清理本次测试进程。

## Acceptance

默认双方 ID 正确；新增角色具有效蒙皮、正面朝向及脚底接地；双方选择与角色名字、头像同步；命中/格挡/HP/KO 仍读取未改动的战斗时间轴；普通与教堂均可运行；展示记录实际结果和剩余素材限制，不以源码测试代替原生验收。

已完成代码、构建与核心内容验收；自动诊断程序退出清理滞留未归因，明确记于 `docs/character-roster-validation.md`，不标为通过。测试发现并修复了录制提前跳过KO、同步加载导致开场计时跳跃，以及旧VRM换角后的共享SpringBone资源滞留。
