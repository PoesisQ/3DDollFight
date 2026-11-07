# Combat balance implementation plan

**Goal:** 完善普通攻击的空间判定、伤害区间和可见的回合/比赛结果。

**Architecture:** Python 统一结算并导出快照；浏览器和 Unity 只展示权威结果。碰撞、回合和展示三个任务分别修改独立文件，最后集成验证。

**Tech Stack:** Python/NumPy/pytest、Three.js、Unity 6000.3 C#。

设计依据：`docs/superpowers/specs/2026-11-06-combat-balance-design.md`。现有场景改动保留；在当前工作区执行以免丢失未提交场景。

## Task 1: 碰撞伤害

Files: `src/dollfight/combat.py`、新建 `src/dollfight/combat_rules.py`、`tests/test_combat_balance.py`、按新伤害更新 `tests/test_duel.py`。

- [x] 先写行为回归并运行，确认未实现规则失败。例如同帧双方攻击躯干，断言双方血量都下降；重复 ID 再提交后血量不变；脚尖进入躯干而踝骨尚在外侧应命中。
- [x] 集中定义九类动作区间、基准伤害、受击部位修正和防守消耗。`attack_spec('left_side_kick')` 返回 `damage_min=13, damage_max=19`。
- [x] 以脚部胶囊/头躯干和上下腿胶囊检测，处理有效时段、无效历史、重复事件、按接触时间排序并批量同时结算、破防硬直。
- [x] 运行 `uv run --locked pytest tests/test_combat_balance.py tests/test_duel.py -q`，修正与新增规则相关的旧断言。

## Task 2: 回合规则

Files: 新建 `src/dollfight/match.py`、修改 `src/dollfight/duel.py`、新增 `tests/test_match.py`。

- [x] 先覆盖 KO、双 KO、超时相同 HP 平局、两胜一负、胜场相同平局和 KO 后血量冻结，运行确认规则缺失。
- [x] 实现独立的回合结果和比赛聚合，集成到 `build_duel`，保留原 `rounds[].health` 和其他旧字段。
- [x] 帧输出使用设计中的字段；最后一帧具有完整结果，跨回合重置 CombatResolver，不在结果中泄漏未来胜负。
- [x] 运行 `uv run --locked pytest tests/test_match.py tests/test_duel.py -q`。

## Task 3: 展示和引擎导出

Files: `src/dollfight/animation_export.py`、`tests/test_unity_duel_export.py`、`apps/motion-lab/app.js`、`apps/motion-lab/combat-visuals.js`、`unity/Packages/com.dollfight.humanoid/Runtime/DollFightDemo.cs`、必要的新 Unity 文件及 meta。

- [x] 扩展导出测试：`roundState`、`roundWinner`、`roundRemaining`、`wins`、`matchState`、`matchWinner`、结果标签、格挡和标准判定体数据必须与输入快照一致。
- [x] 导出兼容旧 fixture，Unity 接收 camelCase 字段，显示比分、倒计时、命中/结算原因，提供可切换权威判定体可视化。
- [x] 浏览器显示相同字段，完整播放到末尾停止，Reset 可重新开始。Unity 同样保留最后结果并支持 Reset。
- [x] 运行 `uv run --locked pytest tests/test_unity_duel_export.py -q` 和 `node apps/motion-lab/tests/run-tests.js`。

## Task 4: 集成与验收

- [x] 自审 diff，独立审查伤害上界、编号对称、KO 冻结、导出与渲染数据一致性。
- [x] 运行 `uv run --locked pytest -q`、`uv run --locked ruff check .`、`uv run --locked ruff format --check .`、`uv run --locked python tools/check_contracts.py`、Node 检查。
- [x] 运行 `uv run --locked python tools/prepare_unity.py`，检查实际 2700 帧的每回合结果及事件伤害。
- [x] 用 Unity CLI 编译、EditMode 测试、播放检查并构建本机入口，记录真实执行结果到 `docs/combat-rules.md`，不覆盖旧录像记录。
