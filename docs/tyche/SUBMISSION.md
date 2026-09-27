# 提交清单 / Submission checklist

本清单把赛题要求对应到仓库中的产物，供提交前逐项核对。赛题：CCF BDCI 2026【华为 openJiuwen】基于 JiuwenSwarm 的 Agent 科研论文自动生成（ICLR 模板 Agent 方向短论文，由 Stanford Agentic Reviewer 评审；决赛提交截止 10/09 24:00；前 5 名进行复现审核）。

## 1. 论文

| 要求 | 位置 | 核对方式 |
|---|---|---|
| ICLR 模板短论文 | `workspace/runs/<run-id>/package/paper.pdf`，源码在 `paper_source/` | 使用官方 ICLR 2027 样式文件（`tyche/paper/template/SOURCE.md`）；正文页数见 `run_report.md` 的 Main-text pages（默认上限 5 页，`paper.max_main_pages`） |
| Agent 方向 | 运行的 `--direction`（`memory_engine`、`context_engineering`、`self_evolution`） | 见 [runs/README.md](runs/README.md) |
| 数字与引用可核验 | `gates.json`、`claims.json` | `gates.json` 中 `passed: true`；`run_report.md` 中论断地图应为 0 条未核验 |
| AI 使用声明 | 论文末尾 “AI use statement” | 由代码生成，列出模型、各环节用途与核验方式 |
| 自评 | `tyche review paper.pdf` | 本地 7 维评审团，只作草稿间的相对信号，不是 paperreview.ai 分数的预测 |

提交前由团队成员通读全文：核对结论是否与 `run_record/artifacts/analysis/` 一致、限制讨论是否充分，并按平台要求处理作者信息（模板默认为匿名 “Anonymous authors”）。

## 2. 复现审核（前 5 名）

| 审核内容 | 准备好的材料 |
|---|---|
| 环境 | [REPRODUCE.md](REPRODUCE.md) §1–2；打包目录中的 `environment.json`（Python、平台、openJiuwen 版本与提交、LaTeX 工具版本、git 状态） |
| 无网络、无密钥的端到端验证 | `scripts/tyche/install_dev.sh` → `tyche selftest`（8 个阶段 + 真实 LaTeX 编译） |
| 一键离线核验 | `tyche verify <打包目录>`：产物哈希、PDF、重算统计量与允许数字登记表、正文数字、引用来源、论断地图，全部通过时输出 `verify: PASSED` |
| 论文数字的重新推导 | `tyche run --resume --run-id <run-id> --from-stage analysis --stop-after analysis`，只运行确定性代码，同一种子得到相同的统计量与允许数字登记表 |
| 实验原始输出 | `run_record/artifacts/experiment_results/`（含逐条目 `per_question`）、`run_record/artifacts/experiment_code/`（openJiuwen 智能体编写并执行的代码） |
| 过程可追溯 | `provenance.json`（每个产物版本的输入、父版本、SHA-256 与漂移检查）、`review_ledger.json`、`run_record/`（事件、用量、运行配置） |
| 重新生成整篇论文 | [REPRODUCE.md](REPRODUCE.md) §4；规划、写作与评审由模型生成，重跑不会逐字一致，这一点在该节中说明 |

## 3. 原创性与知识产权

- 仓库基于 openJiuwen JiuwenSwarm（Apache-2.0）；Tyche 新增代码与上游改动范围见 [NOTICE.md](../../NOTICE.md)。
- 参考文献只来自学术 API 并经 `tyche/literature/verify.py` 核验，模型不提供任何书目信息；结果数字只来自 `tyche/analysis`。
- 自检夹具明显虚构（arXiv 编号 `0000.*`，作者 Fixture/Testcase），不会出现在真实论文中。
- Web 工作台的第三方依赖及许可证文本随构建产物输出到 `tyche/web/frontend/dist/THIRD_PARTY_NOTICES.txt`。

## 4. 需要向赛事平台确认的事项

- 提交形式：仅 PDF，还是同时提交代码仓库链接或压缩包；代码仓库是否需要公开。
- 作者信息：是否需要去匿名化，以及团队信息的填写位置。
- 复现审核时提供的运行环境（是否可联网、是否提供模型端点），以决定审核方重跑到哪一步：`tyche selftest` 与重新分析都不需要网络和密钥。
