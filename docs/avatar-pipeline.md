# 二次元皮套：生成、绑定与动作验收

2026-10-23。已准备接入工具和首个角色配方，**尚未生成新角色，也没有获得 SkinTokens 输出**。当前 Motion Lab 中的皮套仍是 `data/avatars/sample.json` 指定的官方公开样例。

## 采用的路线

先用 Tripo 生成角色网格和贴图，再比较自动绑定；保留同一个网格和同一段真人动作，单独判断骨骼与蒙皮质量。SkinTokens 的 TokenRig 接收已有网格，预测骨架和蒙皮权重，也支持固定已有骨架只预测权重。它适合我们的绑定研究环节。[Tripo 生成接口](https://developers.tripo3d.ai/en/docs/generation-text-to-model/standard)、[SkinTokens 项目](https://zjp-shadow.github.io/works/SkinTokens/)

```text
角色外形 / 扫描网格
  → 检查拓扑、尺度、朝向与绑定姿态
  → Tripo 自动绑定 / TokenRig / 人工参考绑定
  → 骨骼语义映射、VRM 导出
  → 本仓库结构检查
  → 同一真人动作重定向
  → 肩胯变形、支撑脚、衣物和玩家视角验收
```

我们的课程工作落在坐标与绑定姿态统一、骨架语义映射、全身重定向，以及蒙皮的可重复比较。生成工具只提供资产，不能替代这些步骤。先用预训练模型做离线处理，不把生成模型放入实时对战循环，也暂不自建训练集重训。

## 第一份角色配方

[`anime-fighter.recipe.json`](../data/avatars/anime-fighter.recipe.json) 固定了原创成年动漫格斗者的外观、T-pose、约 3 万面目标、模型版本、种子和五段验收动捕。短发、短外套、裤装用于第一轮，先能看清肩胯与腿部变形；之后再增加长发、裙摆等难例。

文件包含可审核的 Tripo 生成请求体，以及绑定检查和绑定请求的模板。**没有执行付费请求**；模板中的 `<generated_task_id>` 需要真实生成结果，不能原样提交。绑定显式选择 `v3.0-20260909`。`spec: vrm` 指骨骼命名约定，输出仍可为普通 GLB；必须检查 humanoid 扩展，不能改后缀冒充 VRM。[Tripo 绑定接口](https://developers.tripo3d.ai/en/docs/animations-rig)

实际生成需要接入 Tripo 账户。当前插件目录检索没有找到 Tripo，本机也未配置其 CLI/API 访问。官方提供浏览器设备登录方式；账户接通后先确认这一份配方的点数消耗再提交，不需要把密钥贴入聊天。[官方接入方式](https://developers.tripo3d.ai/en/docs/codex-plugin)

## 已完成的结构检查

```powershell
uv run --locked python tools/check_avatar.py data/raw/avatars/sample.vrm --output outputs/avatar-audit.json
# 对自己的内嵌资源 GLB / VRM 使用相同命令，替换文件路径。
```

此命令仅在本机读文件。检查 GLB 边界、关节树、VRM 语义映射、蒙皮索引、权重归一化、逆绑定矩阵与非有限数值，支持 strided accessor 和归一化整数权重。索引按 `skin.joints` 的局部序号解释，不能当作全局 node 编号。

报告分别给出 `errors`、`warnings` 和 `motion_lab_structural_candidate`。退出码 0 表示未发现这些结构错误；**普通 GLB、静态网格、缺少本检查器所需关节的 VRM 也可能返回 0，但候选状态为 false**。当前浏览器映射要求 19 个关节，多于 VRM 的最小要求。超出四个影响或使用额外权重集时，需要离线整理后重新检查。

这不是完整 glTF/VRM 标准验证器：不展开 sparse/compressed 数据，不判断外观、模型许可、表情、材质兼容性或骨骼位置是否符合人体。`visual_quality_verified` 始终为 false；它不会自动修复或把普通 GLB 转成 VRM。

公开样例本次实测：24,951 个蒙皮顶点，3 个 skin，所需 19 个关节齐全，每顶点最多 4 个影响；权重和与 1 的最大偏差约 `1.79e-7`。完整机器报告见 [`experiments/sample-preflight.json`](../data/avatars/experiments/sample-preflight.json)。

## SkinTokens 本次实测与复现

在官方匿名 Hugging Face 演示上，用哈希固定的公开样例尝试了一次“保留已有骨架，只重算权重”，没有上传真人数据。服务在 GPU 分配时返回：

> The requested GPU duration (450s) is larger than the maximum allowed

没有下载到输出文件，不能据此判断算法的质量或速度，也没有自动重试。参数、输入哈希和错误保存在 [`experiments/skintokens-hosted-20261023.json`](../data/avatars/experiments/skintokens-hosted-20261023.json)。它是托管服务实验；检查过的源码 commit 并不证明该服务运行同一版本。

复现命令会再次上传**这一个公开样例**并尝试服务；仅在外部限制变化后手动运行：

```powershell
uv sync --locked --group assets
uv run --locked --group assets python tools/try_skintokens_sample.py --timeout 180
# --full-rig 同时预测骨架；默认只预测已有骨架的权重。
```

脚本校验样例 SHA-256，未通过就不联网；生成记录与输出保存在忽略目录 `outputs/avatar-experiments/`。它不自动读取登录 token，不自动重试，得到文件也只标记 `downloaded_unvalidated`。`assets` 是可选依赖组，日常演示不需要安装 Gradio。

官方本地推理要求 Python ≥3.11、CUDA ≥12.1 和至少 14 GB 显存；本机 RTX 4060 Laptop 为 8 GB。本仓库实时端使用 Python 3.10，因此后续 GPU 推理应采用独立 uv 环境，记录源码 commit、依赖与权重 hash，不把 CUDA 依赖混进实时端。当前尚未完成这个 GPU 环境的部署或验证。[官方安装与用法](https://github.com/VAST-AI-Research/SkinTokens/tree/273b691d35989d71cd17ff2895fdc735097b92d1)

## 如何比较，避免“能动就算成功”

1. 保存原始网格、原始绑定和转换后的 VRM，记录各自 hash。先统一实际尺度、正面方向、T/A-pose 与骨骼语义；修改 bind pose 时一并更新逆绑定矩阵。
2. 先比较“同一骨架、不同权重”，再比较“不同骨架和权重”，区分骨骼预测错误与蒙皮错误。确认顶点顺序和骨骼对应一致后才能计算权重 L1 差；否则不能直接逐行相减。原始样例权重只作工程参考，不冒充绝对真值。
3. 用回旋踢、前踢、拳击、下段格挡和手刀防御，在相同时间、机位、光照下检查正面、侧面、背面。0.25× 检查转髋、肩窝塌陷、提膝时胯部拉扯、肘膝弯折、脚滑和衣物穿插。
4. 给每个候选保留失败帧和判定，不只留漂亮的静态截图。结构报告、浏览器实际回放和 Unity Humanoid 导入分别记录；本机尚无 Unity Editor，不能把浏览器通过当成 Unity 已验收。

机器报告和文本配方进普通 Git；模型二进制按仓库 LFS/共享存储约定交付。生成权重、原始扫描与过程输出不强制加入 Git。资产交接必须包含来源/许可、hash、骨骼映射、绑定姿态和验证片段，避免同名文件在组员机器上内容不同。
