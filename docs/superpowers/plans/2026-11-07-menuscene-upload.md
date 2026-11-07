# menuscene 上传与地图恢复 Implementation Plan

> **For agentic workers:** Execute the documentation and ignore task as one unit, then review the staged result before committing and pushing. Track completion with the checkboxes below.

**Goal:** 将当前选角、选场等项目内容上传到 `menuscene`，保留本地地图数据，并让新克隆能准确恢复缺失资源。

**Architecture:** 普通 Git 保存源码、Unity 场景、配置、资源来源和恢复清单；现有 LFS 保存角色与通用贴图。教堂和 Cloud 扫描及对应预览图保持忽略，目标目录内提交恢复说明和必要的 Unity 元数据。地下竞技场预览图随菜单提交。

**Tech Stack:** Git / Git LFS, Unity 6000.3.27f1, Python / uv, Node.js.

## 任务与验证

- [x] 检查当前改动、远端分支和缺失地图路径，从当前 HEAD 创建 `menuscene`，保留所有工作区内容。
- [ ] 整理 `.gitignore`：忽略生成内容与外部地图，允许恢复说明及地图目录元数据，提交地下竞技场预览图。
- [ ] 新增 `docs/map-assets.md` 与 `data/environments/restore-manifest.json`，记录地图、预览图的目标路径、大小、SHA-256 和恢复方式；缺失地图目录内保留 README 与对应 `.meta`。
- [ ] 更新根目录 README、Unity README、教堂与菜单文档，明确首次克隆缺少地图、已转换产物可直接恢复、原件可用准备脚本重建。
- [ ] 复核恢复路径和实际代码一致，校验清单哈希与本地资源一致，检查 Git 忽略结果、LFS 指针与暂存文件，无扫描数据、构建或缓存进入提交。
- [ ] 运行仓库 CI 对应的 Python 测试、Ruff、协议校验、前端测试；本次不修改运行时代码，不为文档和忽略规则新增测试。
- [ ] 审查暂存差异，提交当前项目内容，推送 `origin/menuscene`，核对远端提交与本地 HEAD 一致。

## 完成判据

新克隆包含源码、场景、角色和通用美术资源；运行教堂与 Cloud 前的额外资源、目标位置和校验方式均可从 README 找到。仓库中保留地图目录位置，扫描文件和受限预览图仍在本地且未进入 Git。分支推送成功且工作区无未提交项目改动。
