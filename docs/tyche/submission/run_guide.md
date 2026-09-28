# 复现指南

本目录是 Tyche 的代码快照，对应代码仓库 <https://github.com/sweetcornna/Tyche> 中提交包 README 所写的提交。复现分三个层次，由易到难：

1. 离线核验提交论文中的每个数字与引用（几分钟，不需要网络和模型）；
2. 离线运行完整流水线自检（不需要网络和模型）；
3. 用真实模型重新生成论文（需要模型 API 与学术 API，耗时数小时）。

## 1. 环境

| 组件 | 版本 | 用途 |
|---|---|---|
| Python | 3.11（3.11–3.13 均可） | Tyche 与 openJiuwen |
| [uv](https://docs.astral.sh/uv/) | ≥ 0.5 | 按锁定版本安装依赖 |
| TeX Live | 2023 及以上：`latexmk`、`pdflatex`、`bibtex` | 编译 ICLR 2027 论文 |
| poppler | `pdftotext`、`pdfinfo` | 页数门禁、PDF 文本抽取 |
| 操作系统 | macOS 或 Linux | 示例运行使用 macOS（arm64） |

- Ubuntu：`sudo apt-get install -y latexmk texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended poppler-utils`
- macOS：`brew install texlive poppler`

安装依赖：

```bash
cd code
./setup_env.sh               # 创建 .venv，按 requirements.txt 安装全部锁定依赖（--no-deps，不重新解析）
source .venv/bin/activate
```

`requirements.txt` 是仓库 `uv.lock` 导出的完整依赖，其中 openJiuwen agent-core 固定在提交 `9e3390195a9ea15235b2b5f7412cb2aa440622cc`。如果 gitcode.com 不可达，脚本会改用 GitHub 官方镜像（github.com/openJiuwen-ai）上的同一提交；它还会获取该提交的 SDK 参考文档，实验阶段的编码智能体需要读取这些文档。

也可以直接使用完整仓库，它包含 JiuwenSwarm 与蜂群技能的集成：

```bash
git clone https://github.com/sweetcornna/Tyche && cd Tyche
git checkout <提交包 README 中的提交>
scripts/tyche/install_dev.sh && source .venv/bin/activate   # 之后用 tyche 命令代替 python main.py
```

## 2. 离线核验提交的论文（不需要网络与密钥）

```bash
python main.py verify ../evidence/<run-id>
```

该命令只读取打包目录，不调用模型，逐项检查：

- 每个产物版本的 SHA-256 与溯源记录一致；
- `paper.pdf` 与打包时记录的一致；
- 由打包的实验指标文件、计划与实验设计重新计算统计量和允许数字登记表，结果与打包内容逐字节一致；
- 正文受检章节中的每个数字都匹配某个计算值；
- 每个引用都来自已核验的文献记录；
- 论断–证据地图可以重建，且没有未核验的论断。

全部通过时，最后一行输出 `verify: PASSED`，任何一项失败则退出码为 1。

需要人工核对时可以查看以下位置：

| 内容 | 位置 |
|---|---|
| 实验原始输出（含逐条目结果） | `run_record/artifacts/experiment_results/` |
| openJiuwen 智能体编写并执行的实验代码 | `run_record/artifacts/experiment_code/` |
| 实验设计 | `run_record/artifacts/experiment_design/` |
| 统计结果与允许数字登记表 | `run_record/artifacts/analysis/`、`run_record/artifacts/numbers/` |
| 论文句子到证据的映射 | `claims.json` |
| 评审发现台账 | `review_ledger.json` |
| 门禁结论 | `gates.json` |
| 每次模型调用的用量 | `run_record/usage.jsonl` |
| 事件日志 | `run_record/events.jsonl` |

## 3. 离线自检与测试（不需要网络与密钥）

```bash
python main.py selftest      # 8 个阶段 + 真实 LaTeX 编译，使用虚构夹具，结尾输出 selftest: PASSED
python -m pytest             # Tyche 的离线测试（pytest.ini 只收集 tests/tyche）
```

自检使用的文献与实验数据是明显虚构的夹具（arXiv 编号以 `0000.` 开头，作者名为 Fixture / Testcase），不构成研究结论。自检会对它自己的打包目录运行与第 2 节相同的核验。

## 4. 配置模型

在 `code/` 下创建 `.env`（不要提交到任何地方，建议 `chmod 600 .env`）：

```
API_KEY=...                  # 只放在 .env 或环境变量中；Tyche 不会把它写入配置、日志或产物
API_BASE=https://<OpenAI 兼容端点>/v1
MODEL_NAME=<模型名>
MODEL_PROVIDER=OpenAI
MODEL_CONTEXT_WINDOW=<上下文窗口 token 数>
S2_API_KEY=...               # 可选：Semantic Scholar，减少限流
OPENALEX_API_KEY=...         # 可选：OpenAlex
```

`python main.py doctor --ping-model` 会检查以下各项：

- 工具链；
- 密钥是否已设置（只报告有无，不显示内容）；
- 文献源是否可达；
- 模型端点是否可达。

## 5. 用真实模型重新生成论文

`config.yaml` 是生成提交论文时的完整运行配置，模型端点从 `API_BASE` 读取。本节末尾给出了本论文使用的题目、方向与命令。

```bash
# 规划后暂停，可人工检查研究计划
python main.py run --config config.yaml --run-id <新运行编号> --topic "<题目>" --direction <方向> --stop-after plan
# 继续：文献调研 → openJiuwen 实验 → 分析 → 写作 → 评审修订 → 经验演进 → 打包
python main.py run --resume --run-id <新运行编号>
python main.py verify workspace/runs/<新运行编号>/package
```

也可以用 `python main.py ui` 打开本机工作台，在浏览器中发起、审批和跟踪运行。

**可复现性的边界**：规划、写作与评审由大模型生成，实验代码由 openJiuwen 智能体编写并真实执行，这些环节重跑不会逐字一致。Tyche 保证的是：给定同一份实验指标文件，统计结果、表格、图、允许数字登记表与门禁结论完全确定（固定随机种子），论文中的每个数字都能追溯到这些计算值，每个引用都来自核验过的学术 API 记录。第 2 节的核验就是对这一点的检查。
