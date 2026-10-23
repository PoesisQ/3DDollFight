# 二次元皮套：生成、绑定与动作验收

2026-10-24 更新。**默认路线已更换为“许可明确的、已绑定 VRM 底模 → 独立服装/头发编辑 → 动作与表面共同验收”。** 旧 Hunyuan 单图生成 + 规则蒙皮因视觉不合格而退出默认演示，仍留作可复现对照。

## 为什么旧模型不合格

问题来自资产结构，不只是渲染器或某个平滑参数：原始形体是穿衣外表面，缺少可靠的隐藏身体、衣物分层与关节拓扑；正面图投影不能提供真实侧背面纹理；裙子使用骨盆/双大腿混合权重，跨步和高踢会把两腿之间的面拉长；固定 19 关节缺少手指、发束、裙板和扭转辅助骨。约 20 万三角面的密度并没有补上这些信息。骨骼 FK 残差为零仅能验证骨骼跟随，不能验证皮套。

因此，不继续将这份网格反复自动绑定当作主线。Tripo 的纹理/拓扑能力仍可试验，SkinTokens 仍适合在固定输入网格上研究权重，但它们是否能满足本项目裙装大幅动作，须以实际输出判定；此前失败的托管调用不作为工具质量结论。

## 当前可运行的替换版本

`data/avatars/atelier/nozomi.vrm`、`mizore.vrm` 为 **希美/霙方向的校服外观草稿**，不是已通过相似度验收的成品。底模来自 [VRM Consortium 官方样例](https://github.com/vrm-c/vrm-specification/tree/master/samples/VRM1_Constraint_Twist_Sample)，© 2022 pixiv Inc.；嵌入许可允许修改及再分发，原始许可见 [sample.json](../data/avatars/sample.json)。采用已有可动画拓扑，是本轮实际落地路线；没有声称运行了 VRoid Studio 或 Tripo。

- 保留身体、脸、眼的原始网格/UV/权重，54 个 humanoid 映射（其中 19 个由本项目人体输入驱动）、手指与扭转辅助骨。手指姿态仍是展示先验，非摄像头测量。
- 头发长度/束形编辑与骨骼位置同步，按变换更新对应逆绑定矩阵；身体原有逆绑定偏移完整保留。头发使用独立 MToon 颜色，避免原贴图的棕色高光污染深蓝发色；源纹理文件没有改写。
- 上衣缩短与袖型调整，增加真实的前/后水手领、领巾；袜口切面平整并保留身体蒙皮。原有打底短裤保留。
- 裙子单独建模：16 褶、896 顶点，白色裙边为独立面片材质。VRM 中有 16 条裙板骨链，裙子不混合两条大腿权重。每套目前 39,317 三角面，约 11.4 MB。
- 浏览器把裙子替换为同拓扑的独立动态表面：60 Hz 缓存、240 Hz 内部位置约束子步，含腰圈固定、结构/剪切/弯曲距离约束、两侧大腿/小腿胶囊与地面碰撞。接触方向连续化减少快速抬腿时相邻点被推到胶囊两侧的问题；不可伸长约束优先于互相冲突的碰撞约束，剩余穿插单独报告。头发/上衣使用底模已有的 VRM spring bones。预热首帧后烘焙缓存，回放只插值，暂停/倒拖/变速可复现。

```powershell
git lfs pull
uv sync --locked
uv run --locked python tools/fetch_avatar.py
# 以下纯离线，输入 SHA 固定；不上传图像，不需要 GPU 或账号
uv run --locked python tools/build_template_avatars.py
uv run --locked python tools/check_avatar.py data/avatars/atelier/nozomi.vrm
uv run --locked python tools/check_avatar.py data/avatars/atelier/mizore.vrm
uv run --locked pytest tests/test_template_avatars.py -q
node apps/motion-lab/tests/run-tests.js
uv run --locked python -m dollfight.server --open
```

打开 `/avatar-review.html`，默认三列分别为旧希美、新底模 A、新底模 B。可切绑定姿态、拳击、前踢、下段格挡、回旋踢，切正/侧/背面和面部近景，并开关衣发求解。它们用相同动作时刻、各自的真实骨长；不是同一个网格的 A/B 权重实验。选择「希美 / 霙 · 加入 Tripo 原件」可比较该角色的旧方案、可动底模、Tripo 静态外观；Tripo 原件不随动作选项运动，界面明确标注。`导出本次皮套检查数据` 保存当前条件与约束应变诊断。诊断不是美术合格判定。

目前不包含布料自碰撞、手臂/躯干完整网格碰撞、对战根节点水平加速引起的惯性；腰部与极端姿态仍可能穿插或拉伸。裙布缓存仅在浏览器使用，VRM 里的 spring bone 备用链不等价于同一布料算法，Unity 适配器尚未驱动这些次级运动。脸型、刘海、高马尾结构和原作制服比例仍须精修；不把底模换装冒充已经完成角色还原。

整段 CMU 组合回放的压力检查中，初版裙布最大约束长度比达到 13.58；加入接触方向连续化、子步与拉伸限制后降至 1.154，平均绝对应变约 2.81%。但高踢 4.95 s 仍有 9.78 cm 的最大代理胶囊穿入，约 5.89% 的自由顶点在该帧穿入超过 5 mm。因此**仅通过防拉裂检查，未通过完整衣物碰撞验收**；代理胶囊深度不是精确网格相交深度。后续应修正腰圈与高抬腿的几何冲突、使用裙装姿态修正形状，并增加连续面碰撞，不能通过继续放大碰撞半径或隐藏统计来宣称成功。

资产 hash 与构建说明保存在 [atelier/manifest.json](../data/avatars/atelier/manifest.json)。原始样例许可、角色原作权利、项目修改代码分别归属；资产不因仓库代码许可而变成可任意商用的原创角色。

[2026-10-24 实际检查记录](../data/avatars/experiments/avatar-route-review-20261024.json) 保存模型 hash、失败指标和截图索引。同一页面按 7.7 → 9.8 → 7.7 s 往返后，整页截图字节一致；这验证了该输入下的时间采样复现性，不代表衣物物理真实。Python 96 项与 JavaScript 8 项本机检查通过；Unity、实机相机和正式美术验收仍未通过或未执行。

## v0.5 单图生成试穿记录（已退出默认）

外观依据来自[电影官网](https://liz-bluebird.com/)的[希美角色图](https://liz-bluebird.com/img/character/nozomi.png)与[霙角色图](https://liz-bluebird.com/img/character/mizore.png)。先用图像生成工具制作各一张正面 T-pose，再在腾讯官方 `tencent/Hunyuan3D-2` 匿名演示调用形体生成；随后本机归一到 1.72 m，建立 19 骨骼、逆绑定矩阵、四影响权重和 VRM humanoid 映射。

[`liz/provenance.json`](../data/avatars/liz/provenance.json) 记录输入图/原始网格 hash、服务参数、输出和限制；[`liz/generated.json`](../data/avatars/liz/generated.json) 记录转换后的资产。原始生成 PNG、未绑定 GLB 和 VRM 都用 LFS 保存，避免覆盖原件后无法比较绑定方案。角色与官方参考画的原始权利仍属于各自权利人，本仓库没有为它们另行授予商业许可。

生成网格分别约 19.3 万和 20.5 万三角面。绑定采用人体区域约束的距离权重，再沿实际网格邻接扩散，消除区域边界的权重突变；小腿骨干只跟随小腿骨，权重混合限制在膝/踝附近，以修正踢腿时的小腿弯曲鼓包。它没有学习到人体组织或衣物运动。正面纹理直接引用原始 PNG，背面暂用分区颜色。完整贴图接口另作一次尝试，托管服务返回 `AppError: NameError`，未取得完整贴图；没有执行付费请求。

```powershell
git lfs pull
uv sync --locked --group assets
# 纯离线重建，不调用生成服务
uv run --locked --group assets python tools/build_liz_avatars.py
uv run --locked python tools/check_avatar.py data/avatars/liz/nozomi.vrm
uv run --locked python tools/check_avatar.py data/avatars/liz/mizore.vrm
# 以下才会重新上传指定角色的生成参考图，手动按需执行
uv run --locked --group assets python tools/try_hunyuan_avatar.py nozomi
```

旧模型仍可分别选择单模型，切到“皮套近看”，用静态 T-pose 和真人回旋踢检查。[视觉检查记录](../data/avatars/experiments/liz-visual-review-20261023.json) 和 [3.80 s 裙摆失败帧](../data/avatars/experiments/liz-skirt-failure-20261023.png) 随仓库保存；当前正式美术验收结论为不通过。实际骨骼映射位置残差与蒙皮外观分别观察：前者为零，也不能证明后者合格。长裙高踢时仍可能拉伸、穿插；手指未独立绑定，不能自然握拳；面部和侧背面相似度、发梢、裙摆、隐藏身体拓扑仍需完善。结构报告不是正式美术验收，也没有完成 Unity Editor 验收。


## 保留的生成与绑定研究支线

### 2026-10-24 Tripo Studio 免费方案实测

两份参考图均已通过 Studio 正常上传、以 H2.5 生成并正常导出。原始 GLB、低面版本、SHA-256、来源与积分记录见 [`tripo/provenance.json`](../data/avatars/tripo/provenance.json)。希美原件 237,752 面；普通三角面重拓扑得到 39,996 面；霙原件 270,156 面。生成各 40 免费积分，希美重拓扑实际页面价 5、VRM Humanoid 自动绑定 20，共消耗 105 免费积分，观察余额 95，未充值或订阅。

**本次发现免费绑定与免费绑定导出是不同权限。** 希美在 Studio 完成绑骨，但导出面板的「导出骨骼」开关禁用，旁边按钮打开订阅页。正常免费导出的 GLB 仍声明 55 个 skin joints，却没有关节位置：所有关节重合，99.9923% 的权重质量落到一个根节点。因此没有把它包装成可用 VRM，也没有再为霙消耗绑定积分。现有原件只能用于外观检查；可动角色继续使用授权 VRM 底模。付费与本地绑定路线都需要另行取得有效输出后验证，不能根据网页动画推断本地文件可用。

对照页提供 Tripo「原始 PBR / 哑光预览 / 仅贴图」三种材质观察方式；后二者只在浏览器替换着色材质，不改原始 GLB、纹理或几何。统一显示身高 1.65 m 便于比较，不意味着重建出角色真实身高。面部凹凸、发丝结构和裙装活动空间仍未通过外观与动作验收。

在研究支线中可用 Tripo 生成角色网格和贴图，再比较自动绑定；保留同一个网格和同一段真人动作，单独判断骨骼与蒙皮质量。SkinTokens 的 TokenRig 接收已有网格，预测骨架和蒙皮权重，也支持固定已有骨架只预测权重。它适合我们的绑定研究环节。[Tripo 生成接口](https://developers.tripo3d.ai/en/docs/generation-text-to-model/standard)、[SkinTokens 项目](https://zjp-shadow.github.io/works/SkinTokens/)

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

官方 CLI 0.7.3 已在 `tools/tripo-cli/` 固定依赖；2026-10-24 本机设备授权完成，但开发者账户余额为 0。Studio 网页账户另有 200 免费积分；免费导出需选 H2.5，H3.x 的试用生成不能直接当作可下载资产。`npm ci --prefix tools/tripo-cli` 可单独恢复依赖，认证保存在用户目录，密钥不得写入仓库。日常本地回放不依赖 Tripo 账号。[官方接入方式](https://developers.tripo3d.ai/en/docs/codex-plugin)、[官方计划与积分说明](https://www.tripo3d.ai/product-doc/getting-started/pricing-credits)

## 已完成的结构检查

```powershell
uv run --locked python tools/check_avatar.py data/raw/avatars/sample.vrm --output outputs/avatar-audit.json
# 对自己的内嵌资源 GLB / VRM 使用相同命令，替换文件路径。
```

此命令仅在本机读文件。检查 GLB 边界、关节树、VRM 语义映射、蒙皮索引、权重归一化、逆绑定矩阵与非有限数值，支持 strided accessor 和归一化整数权重。索引按 `skin.joints` 的局部序号解释，不能当作全局 node 编号。v2 额外计算绑定层级的关节空间跨度、单关节权重集中度；多关节全部重合时禁止标为可驱动候选，归一化权重不能掩盖占位骨架。

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
