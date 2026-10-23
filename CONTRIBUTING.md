# Git 与 uv 协作规范

GitHub 远端为 [PoesisQ/3DDollFight](https://github.com/PoesisQ/3DDollFight)，本地使用 `origin`。仓库已提供协作约定与 CI 文件；保护分支、必需的 PR 检查和 LFS 存储设置仍需在 GitHub 确认。配置文件的存在不代表这些远端规则已经生效。

## 仓库组织

如果整个小组尚未建立项目，建议单主仓库按模块分目录，协议、回放样例、核心算法、引擎工程和资产清单一起版本化。暂时不需要微服务式多仓库、长生命周期 develop 分支或 Python 多包 workspace。

若其他组已有独立仓库，不要求他们迁移：将协议、fixture 和模型映射作为有版本的交付物，消费端声明兼容版本。不要靠私聊转发某个 Python 文件或无版本压缩包联调。

当前实际目录：

```text
src/dollfight/          协议、几何、骨架约束、识别、重定向与本地回放服务
apps/motion-lab/        Three.js 评估界面、固定渲染依赖与投影测试
data/samples/           可再分发的小型公开动捕与来源记录
tests/fixtures/         小型合成协议消息
tools/                 校验、数据转换、消融评估与资产重建
docs/                  技术设计、选型、接口和评估记录
.github/               CI 与 PR 模板
pyproject.toml         Python 直接依赖与工具配置
uv.lock                已解析依赖版本
```

Motion Lab 用浏览器完成数值与视觉联调；以后按需增加 `apps/unity/` 或 `apps/godot/` 中的一条正式路线。算法不应直接依赖引擎对象；更换引擎后保留同一输入回放与 FK/事件回归。

## 分支与评审

采用 main + 短期 feature 分支，main 保持可复现。按工作内容命名，如 `feat/retarget-arm-ik`、`fix/depth-alignment`、`docs/pose-contract`。同一个功能提交尽量只涉及一个明确问题；协议改变可合理跨模块。

日常开发的一般流程：

```powershell
git switch main
git pull --ff-only
git switch -c feat/retarget-arm-ik
# 修改并验证
uv sync --locked
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
git add src/dollfight tests docs
git commit -m "feat(retarget): constrain arm IK to target bone lengths"
git push -u origin feat/retarget-arm-ik
# 在远端创建 PR，查看测试和 diff 后合并
```

上面的 `git add` 按实际改动路径选择，不机械地把别人的改动一起提交。共享分支不强推；私人未共享分支可按团队约定整理提交。冲突在本地解决并重跑相关验证，不覆盖另一个模块的实现来“消掉冲突”。

建议远端 main 要求 PR、至少一次他人 review、核心 CI 通过并禁止强推。保护能力可能受平台/仓库方案影响；在实际远端设置并确认，而不是只写在文档中。[GitHub 官方保护分支说明](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)

接口变化需要生产方与消费方共同检查；这是一条协作规则，不重新指定任何人的分工。每个 PR 描述行为变化、接口/资产影响和真实验证结果。稳定演示版本打 tag，并保留相应录制 manifest 与配置。

## Python 依赖由 uv 管理

```powershell
uv sync --locked                  # 恢复已提交依赖，不偷偷重算锁文件
uv add <package>                  # 增加运行依赖并更新 lock
uv add --group dev <package>      # 增加开发工具
uv run --locked pytest -q
```

提交 `pyproject.toml`、`uv.lock`、`.python-version`；不提交 `.venv/`、缓存、全局安装包或机器私有路径。不用 `pip freeze` 覆盖项目定义，也不手工编辑锁文件中的版本/hash。uv 的项目模型和 lock 工作方式见[官方文档](https://docs.astral.sh/uv/guides/projects/)。

`uv.lock` 冲突先解决 pyproject 的依赖意图，再基于商定的锁版本运行 `uv lock`，检查版本变动并复测。摄像头相关包、OpenCV、MediaPipe 和训练框架在验证兼容性后再加入；避免多个发行包同时提供 `cv2`，不要无理由全量升级 NumPy/CUDA。

SDK DLL、驱动、固件、Unity/Godot、Blender 不由 uv 自动管理。单独记录版本、下载源、hash、安装步骤和验证方式；不提交机器绝对路径。若训练环境的 Python/PyTorch/CUDA 与实时端冲突，再建立独立 `training/` uv 项目和 lock；不强迫演示端安装整套训练环境。

本项目把 uv 缓存放到 `.uv-cache/`，便于受限工作区使用；只影响缓存位置，不改变锁定依赖。Python 3.10.19 是继承课程环境的初始选择，后续统一升级时提交版本变更和验证记录。

## 3D 资产与大文件

本仓库 `.gitattributes` 已声明常见模型/纹理/音频由 LFS 管理。每个克隆先执行：

```powershell
git lfs install --local
git lfs pull
```

Git LFS 把 Git 中的大文件内容替换成指针，实际内容存放在 LFS 服务端；因此远端必须支持并配置 LFS，团队也需考虑配额。仅写 `.gitattributes` 不会迁移已经进过历史的大文件。[Git LFS 官方说明](https://git-lfs.com/)

文本代码、JSON、Unity 文本场景/Prefab、Godot 文本场景普通提交。`.blend/.fbx/.glb`、大纹理与音频走 LFS。大量原始 RGB-D、训练数据和权重保存在共享文件存储，用 manifest + hash 追踪；当前 `data/raw/`、`data/private/`、`models/weights/` 被忽略，不能误以为它们会随 clone 到达另一台电脑。

对于 `.blend` 等不可合并文件，采用明确的编辑交接；如果远端支持 LFS locks 再启用锁定工作流。不要同时修改一个二进制资产后期待 Git 自动合并。

## Unity / Godot 的特别约定

Unity 使用 Force Text 和可见 `.meta`；资源移动时保留对应 `.meta`，否则 GUID 引用会断。提交 Assets、Packages、ProjectSettings，忽略 Library/Temp/Logs/UserSettings 等生成内容；固定 Editor 与 package lock。把大场景拆成小 Prefab/子场景，减少多人同时改同一文件。UnityYAMLMerge 可辅助合并，但需要配置路径并用引擎重新加载检查。[Unity 官方场景协作说明](https://unity.com/blog/author-scenes-and-prefabs-with-verson-control)

Godot 提交 project.godot、`.tscn/.tres/.gd`、`.uid` 和需要的导入配置，忽略 `.godot/`；固定版本，保留导出预设而不提交导出凭据。两种引擎都不能只以“没有语法错误”作为视觉改动验收，需固定回放的截图与实际加载结果。

## 自动化与复现实验

当前 CI 在 Windows/Linux 上配置了 uv 锁文件同步、ruff、pytest、fixture 校验与前端投影数值测试。Python 测试包括 IK、三个体型的 FK/骨长、遮挡、动作回收、转向、体型缩放、真实 CMU 输入及协议往返。本机执行结果以交付记录为准，远端 CI 需推送后实际确认。图形效果还需在 Motion Lab 检查；数值测试不能替代截图与实际操作。

`apps/motion-lab/vendor/` 固定 Three.js 版本、MIT 许可证与哈希，不手工编辑压缩库；升级要一起更新 manifest 并复验。`data/samples/cmu_boxing.json` 是带来源的小型公开测试输入，允许跟随普通 Git；原始 AMC 与个人录制继续放在忽略目录。演示界面启动不应自动拉取网络资源。

每次实验关联 Git commit、依赖 lock、配置、数据划分、相机/标定版本、模型 hash 和随机种子。不要只上传最漂亮的一段视频；同一录制能反复重现改进前后的差别，才适合多人协作和课程答辩。
