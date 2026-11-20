# H3 海洋热点聚合路径稳健性实验

本仓库是“海洋数据挖掘技术”课程实验的公开复现材料，研究一个具体问题：对同一批 AIS 经纬度点，直接编码到目标 H3 分辨率与先编码到细分辨率再回卷，是否会得到同一个最繁忙海区。

## 作者信息

- 姓名：许圣斌
- 学号：22634054
- 专业：电子信息

## 核心创新

本实验把“编码路径”作为独立实验变量，提出由路径分歧率、Top-K 热点集合 Jaccard、Top-1 迁移距离、Bootstrap 入选概率和质量守恒误差组成的海洋热点稳健性检查表。实验使用普通样本、边界压力样本和排名翻转样本，分别检验点级分歧、空间误分和热点排名翻转条件。

## 仓库内容

- [最终 Word 报告](report/22634054许圣斌海洋数据挖掘技术实验报告.docx)
- [AI 协作完整聊天记录](chat/full-conversation.md)
- [实验脚本](src/experiment_h3_path_stability.py)
- [Python 依赖](requirements.txt)
- [实验结果 CSV](outputs/experiment_results.csv)
- [实验结果 JSON](outputs/experiment_results.json)
- [实验图](outputs/path_disagreement.png)
- [运行日志](outputs/latest_run.log)

## 一键复现实验

```bash
python -m pip install -r requirements.txt
python src/experiment_h3_path_stability.py
```

脚本使用固定随机种子，生成可审计的合成样本并输出 CSV、JSON、PNG、SVG 和运行日志。合成数据用于检验 H3 聚合路径差异及排名翻转机制，不直接代表真实舟山港口拥堵或船舶活动强度。

## 主要结果

- 普通样本在 H3 分辨率 7 和 5 下的路径分歧率分别为 5.61% 和 8.92%，但排名第一的热点网格保持不变。
- 边界压力样本在分辨率 5 下的 Top-10 Jaccard 降至 0.50，说明质量守恒不能替代空间归属核验。
- 排名翻转样本中，9.09% 的点发生路径改派，排名第一网格的中心迁移约 2.303 km。

## 证据边界

仓库中的实验结果来自固定随机种子的合成数据。真实 AIS 数据需要在获得课程数据许可后，按照报告中的数据合同、清洗规则和双路径统计方案另行验证。
