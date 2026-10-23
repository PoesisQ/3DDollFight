# 可离线回放的输入

v0.7 新增真实步法（均为 120 → 30 Hz，文件内固定原始 hash）：

| 文件 | 原始试验 | 原站动作名称 | 帧数 |
| --- | --- | --- | --- |
| `cmu_walk.json` | 08_04 | slow walk | 121 |
| `cmu_retreat_punch.json` | 76_01 | walk backwards then attack with a punch | 233 |
| `cmu_backwalk.json` | 76_09 | walking backwards | 397 |
| `cmu_strafe.json` | 69_42 | walk sideways and turn (repeated) | 840（截取前 28 s） |

[08 原站目录](https://mocap.cs.cmu.edu/search.php?subjectnumber=08)、[76 原站目录](https://mocap.cs.cmu.edu/search.php?subjectnumber=76)、[69 原站目录](https://mocap.cs.cmu.edu/search.php?subjectnumber=69)。76_01 是连续真人采集；组合展示中的其他衔接为算法编辑。反向侧移明确标记为镜像步态，不作为新增真人采集。

重建：`uv run python tools/fetch_demo_assets.py --cmu`，然后 `uv run python tools/convert_cmu.py --locomotion`。

`cmu_boxing.json` 是 CMU Graphics Lab Motion Capture Database 的 subject 14、trial 01（boxing）前 24 秒，120 Hz 下采样至 30 Hz，转换为项目 canonical19。

v0.4 新增 subject 135 的完整片段，同样从 120 Hz 下采样到 30 Hz：

| 文件 | 原始试验 | 原站动作名称 | 帧数 |
| --- | --- | --- | --- |
| `cmu_front_kick.json` | 135_04 | Front Kick | 329 |
| `cmu_low_block.json` | 135_05 | Gedanbarai | 615 |
| `cmu_roundhouse.json` | 135_07 | Mawashigeri | 368 |
| `cmu_knife_guard.json` | 135_10 | Syutouuke | 501 |

[subject 135 原站目录](https://mocap.cs.cmu.edu/search.php?subjectnumber=135)。动作类别是原站片段说明，不是逐帧/逐招独立真值；参考游戏攻击窗口保存在 `motion_reference.py`，不传给识别器。

这是 **真实光学动捕的动作**，不是 Gemini/RGB-D 跟踪结果；没有逐拳类别标注，因此不可据此声称真人识别准确率。界面中若叠加噪声/缺失，是单独的可控实验。

来源：https://mocap.cs.cmu.edu/ · https://mocap.cs.cmu.edu/search.php?subjectnumber=14

原始单位依据官方 FAQ 转为米：`(1 / 0.45) * 2.54 / 100`。文件内保存原始 ASF/AMC SHA-256、坐标变换和参考骨长。转换器在 `tools/convert_cmu.py`；原始大文件只留在忽略的 `data/raw/cmu/`。

本样本的参考骨长取片段内中位数，地面取足尖高度的第 2 百分位，是离线资产预处理；不代表在线相机标定已实现。正式 PoseFrame 导入使用起始站立窗口标定，两者的评估前提不同。

v0.4 将中立 T-pose 的脚踝对齐观测地面，修正从屈膝起始姿态标定导致的负脚踝高度。重建：`uv run python tools/fetch_demo_assets.py --cmu`，再运行 `uv run python tools/convert_cmu.py` 与 `uv run python tools/convert_cmu.py --martial`。哈希与转换参数随样本保存，公开小样本普通 Git，原始大文件仍忽略。

致谢：The data used in this project was obtained from mocap.cs.cmu.edu. The database was created with funding from NSF EIA-0196217.

请遵循 CMU 原站的数据使用说明；本仓库不为原始或转换后的数据另行授予许可证，也不单独销售此数据。
