# 可离线回放的输入

`cmu_boxing.json` 是 CMU Graphics Lab Motion Capture Database 的 subject 14、trial 01（boxing）前 24 秒，120 Hz 下采样至 30 Hz，转换为项目 canonical19。

这是 **真实光学动捕的动作**，不是 Gemini/RGB-D 跟踪结果；没有逐拳类别标注，因此不可据此声称真人识别准确率。界面中若叠加噪声/缺失，是单独的可控实验。

来源：https://mocap.cs.cmu.edu/ · https://mocap.cs.cmu.edu/search.php?subjectnumber=14

原始单位依据官方 FAQ 转为米：`(1 / 0.45) * 2.54 / 100`。文件内保存原始 ASF/AMC SHA-256、坐标变换和参考骨长。转换器在 `tools/convert_cmu.py`；原始大文件只留在忽略的 `data/raw/cmu/`。

本样本的参考骨长取片段内中位数，地面取足尖高度的第 2 百分位，是离线资产预处理；不代表在线相机标定已实现。正式 PoseFrame 导入使用起始站立窗口标定，两者的评估前提不同。

致谢：The data used in this project was obtained from mocap.cs.cmu.edu. The database was created with funding from NSF EIA-0196217.

请遵循 CMU 原站的数据使用说明；本仓库不为原始或转换后的数据另行授予许可证，也不单独销售此数据。
