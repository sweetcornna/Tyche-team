# 复现指南 / Reproduction guide

本文说明如何从零复现 Tyche 的安装、离线自检、示例运行，以及如何在不调用任何模型的情况下，从打包产物中重新推导论文里的每一个数字。

## 1. 环境

| 组件 | 版本 | 用途 |
|---|---|---|
| Python | 3.11–3.13（开发与示例运行使用 3.12） | Tyche 与 openJiuwen |
| [uv](https://docs.astral.sh/uv/) | ≥ 0.5 | 按 `uv.lock` 安装锁定依赖 |
| TeX Live | 2023 及以上（`latexmk`、`pdflatex`、`bibtex`） | 编译 ICLR 2027 论文 |
| poppler | `pdftotext`、`pdfinfo`、`pdftoppm` | 页数门禁、论文缩略图 |
| Node.js（可选） | ≥ 20 | 构建 `tyche ui` 前端 |

- Ubuntu：`sudo apt-get install -y latexmk texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended poppler-utils`
- macOS：`brew install texlive poppler`（无需 sudo）

## 2. 安装与离线验证（不需要网络与密钥）

```bash
scripts/tyche/install_dev.sh     # 创建 .venv；gitcode 不可达时改用 GitHub 镜像的同一提交；有 npm 时构建前端
source .venv/bin/activate
tyche selftest                   # 全部 8 个阶段 + 真实 LaTeX 编译，使用虚构夹具数据，结尾打印 selftest: PASSED
pytest tests/tyche               # 离线单元与端到端测试
```

自检使用的文献与实验数据都是明显虚构的夹具（arXiv 编号以 `0000.` 开头，作者名为 Fixture/Testcase），不构成研究结论。

## 3. 模型配置

复制 `.env.example` 为 `.env`（已被 git 忽略，建议 `chmod 600`），填写：

```
API_KEY=...                 # 只放在 .env 或环境变量中，不会写入任何配置、日志或产物
API_BASE=https://<OpenAI 兼容端点>/v1
MODEL_NAME=<模型名>
MODEL_PROVIDER=OpenAI
MODEL_CONTEXT_WINDOW=<上下文窗口 token 数>
S2_API_KEY=...              # 可选，Semantic Scholar，减少 429 限流
OPENALEX_API_KEY=...        # 可选，OpenAlex
```

`tyche doctor --ping-model` 检查工具链、密钥（只报告是否存在）、文献源与模型连通性。

## 4. 复现示例运行

示例论文由 `gpt-6-luna`（最高推理强度）生成，配置见 [configs/reasoning-max.yaml](configs/reasoning-max.yaml)，每个运行的研究备注在 [runs/](runs/)。以记忆引擎方向为例：

```bash
# 规划后暂停，人工检查计划
tyche run --config docs/tyche/configs/reasoning-max.yaml --run-id mem-luna-1 \
  --topic "Supersession-aware agent memory: do provenance-tagged correction chains reduce stale-fact answers under a fixed prompt-token budget?" \
  --direction memory_engine --notes docs/tyche/runs/mem-luna-1.notes.md --stop-after plan
# 批准后继续：文献、openJiuwen 实验、分析、写作、评审、演进、打包
tyche run --resume --run-id mem-luna-1
```

另外两个方向把 `--run-id`、`--topic`、`--direction` 与 `--notes` 换成 [runs/README.md](runs/README.md) 中列出的值即可。也可以用 `tyche ui` 在网页中发起、审批和跟踪同样的运行。

**关于可复现性的边界**：规划、写作与评审由大模型生成，实验代码由 openJiuwen 智能体编写并真实执行，这些环节重跑不会逐字一致。Tyche 保证的是：给定同一份实验指标文件，统计结果、表格、图、允许数字登记表与门禁结论完全确定（固定随机种子），并且论文中的每个数字都能追溯到这些计算值。

## 5. 不调用模型，重新推导论文中的数字

每个打包目录 `workspace/runs/<run-id>/package/` 都自带完整运行记录：

| 文件 | 内容 |
|---|---|
| `paper.pdf`、`paper_source/` | 论文与 LaTeX 源码 |
| `run_record/artifacts/experiment_results/` | 实验产出的 `<variant>.metrics.json`（含逐条目 `per_question`） |
| `run_record/artifacts/analysis/`、`numbers/` | 统计结果与允许数字登记表 |
| `claims.json` | 论断–证据地图：每个含数字或引用的句子 → 匹配的计算值 / 已核验文献与证据卡 |
| `gates.json`、`review_ledger.json` | 门禁结论与评审发现台账 |
| `provenance.json` | 每个产物版本的阶段、输入、父版本与 SHA-256，以及打包时的漂移检查结果 |
| `environment.json` | 打包时的 Python、平台、openJiuwen 版本与提交、LaTeX 工具版本、git 状态、模型公开描述 |
| `run_report.md` | 各轮评审分数、阶段状态、token 与缓存用量 |

一条命令核验整个打包目录（只读、离线、不调用模型）：

```bash
tyche verify workspace/runs/<run-id>/package
```

它检查：每个产物版本的 SHA-256 与溯源记录一致；`paper.pdf` 是打包时记录的那一份；由打包的指标文件、计划、实验设计与证据卡重新计算的统计量和允许数字登记表与打包内容逐字节一致；论文正文受检章节中的每个数字都能匹配计算值；每个引用都来自已核验的文献记录（或评审阶段经同一核验器接纳的文献）；论断–证据地图可由代码重建且没有未核验论断。任何一项不通过时退出码为 1，并在统计量不一致时指出打包所用的代码提交。`tyche selftest` 也会对自己的打包目录运行同样的核验。

也可以在运行目录中重新执行分析阶段（只运行确定性代码，不调用模型）：

```bash
tyche run --resume --run-id <run-id> --from-stage analysis --stop-after analysis
```

新生成的 `analysis`、`numbers` 产物版本应与原版本内容一致（同一随机种子 `analysis.seed`）；旧版本保留在溯源记录中可直接对比。也可以只读地导入分析模块：

```python
from pathlib import Path
from tyche.experiments import read_metrics_dir
from tyche.analysis import analyze
variants = read_metrics_dir(Path("workspace/runs/<run-id>/artifacts/experiment_results/v1"))
print(analyze(variants, plan_metrics=[...], seed=0).to_dict())
```

## 6. Web 工作台

```bash
tyche ui                 # http://127.0.0.1:8765
```

侧边面板的“主张溯源”“修订”“血缘”标签分别展示论断–证据地图、逐轮修订差异、产物谱系与环境快照，内容与打包目录中的文件一致。
