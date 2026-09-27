# Tyche 架构设计文档

Tyche 是基于 openJiuwen JiuwenSwarm（Apache-2.0）源码构建的 Agent 科研短论文生成智能体。给定一个 Agent 方向的研究题目，它依次完成研究规划、文献调研、实验、统计分析、论文写作、模拟评审与修订、经验演进和打包，输出一篇可编译的 ICLR 2027 模板短论文，并附带完整的证据链。

## 1. 设计原则：模型提议，代码核验

论文里最容易出错、也最影响可信度的内容是参考文献和结果数字。Tyche 按职责把系统一分为二：

| 由模型完成 | 由确定性代码完成 |
|---|---|
| 规划智能体：回顾经验、检索已有工作、提交研究计划；检索式、文献相关度判断、证据卡观点、主题归纳 | 计划校验（模式校验与机械检查）、学术 API 检索、元数据核验（arXiv / Crossref 回查）、证据卡引文与摘要逐字比对 |
| openJiuwen 实验智能体：实验设计、编写实验代码、根据失败反思修订 | 真实执行实验代码，收集各变体的指标文件 |
| — | 统计：均值、bootstrap 置信区间、配对置换检验、允许数字登记表、表格与图 |
| 作者智能体：通过工具撰写与编辑章节、按评审修订、修复 LaTeX、压缩篇幅，并委派事实核查 | 工具本身：清洗、逐次编辑后的检查、编译、页数判定、门禁（编译 / 数字 / 引用 / 结构 / 占位符 / 内部术语）；结束前检查；接受或回滚修订 |
| 评审智能体：用只读工具核对数字与被引证据后打分、提出发现；忠实度审计 | 报告校验、发现中的引文核对、台账状态机、综合分与接受检验 |
| 写作经验提炼 | 经验晋升与淘汰的门控 |
| — | AI use statement、复现声明、打包、离线核验 |

模型不能提供任何书目信息或结果数字。证据缺失、失败或无法核验时，阶段以 `StageError` 停止并说明原因；系统中没有用编造内容补位的回退路径。门禁有阻断项时拒绝打包，只有显式传入 `--allow-gate-failures` 才会打包，这时论文文件名与 AI use statement 都会标注 UNVERIFIED。

## 2. 分层结构

```mermaid
flowchart TB
    subgraph 入口层
        CLI["tyche CLI<br/>run · status · verify · review · doctor · lessons · selftest · ui"]
        UI["科研工作台 tyche ui<br/>FastAPI + React"]
        SK["JiuwenSwarm 技能<br/>tyche-iclr-paper（SwarmFlow）· tyche-paper（对话）"]
    end
    subgraph 编排层
        PL["pipeline.py<br/>8 阶段状态机 · 续跑 · 重跑"]
        WS["workspace.py<br/>状态 · 事件 · 不可变产物版本 · SHA-256 溯源 · 运行锁"]
    end
    subgraph 能力层
        P0[planning] --> P1[literature] --> P2["experiments<br/>openJiuwen ManagerRuntime"] --> P3[analysis] --> P4[paper + gates] --> P5[review] --> P6[evolution]
        MEM[("memory<br/>SQLite FTS5 / BM25<br/>上下文装配")]
    end
    subgraph 基础层
        LLM["llm.py<br/>openJiuwen init_model · 用量计量 · 提示缓存 · 重试"]
        CFG["config.py<br/>分层配置 · 环境变量展开"]
    end
    subgraph 证据层
        TR["trace/<br/>论断地图 · 修订历史 · 谱系 · 环境快照 · 离线核验"]
    end
    CLI --> PL
    UI --> PL
    SK --> CLI
    PL --> WS
    PL --> P0
    MEM -.-> P0 & P1 & P4 & P5 & P6
    P0 & P1 & P4 & P5 & P6 --> LLM
    P2 --> LLM
    WS --> TR
```

| 层 | 模块 | 职责 |
|---|---|---|
| 入口 | `tyche/cli.py` | 命令行入口；`run` 按阶段执行并可 `--resume` / `--from-stage` / `--stop-after`；`verify` 离线核验打包目录 |
| 入口 | `tyche/web/` | 本机科研工作台：发起、审批、跟踪运行，12 个视图展示论文、计划、文献、实验、结果、评审、论断地图、修订、谱系等 |
| 入口 | `skills/tyche-iclr-paper`、`skills/tyche-paper` | JiuwenSwarm 蜂群技能与 Agent 模式入口；阶段智能体只执行对应命令并汇报状态，证据规则全部在 `tyche` 内执行 |
| 编排 | `tyche/pipeline.py` | 阶段顺序、输入输出、失败处理、运行报告 |
| 编排 | `tyche/workspace.py` | `state.json`、`events.jsonl`、`artifacts/<name>/v<N>`、`provenance.jsonl`、按运行的排他锁 |
| 能力 | `tyche/agent/` | 智能体运行时：工具协议、权限模式、待办清单、钩子与结束前检查、子智能体、上下文压缩、回滚、转录；论文工作台工具；作者智能体 |
| 能力 | `tyche/planning.py` | 研究计划（研究问题、可证伪假设、方法、基线、指标、贡献、范围限制）；规划智能体 |
| 能力 | `tyche/literature/` | 三源检索、限速与缓存、去重、BM25 预排序、筛选、一跳引文扩展、核验、证据卡、综述 |
| 能力 | `tyche/experiments/bridge.py` | 驱动 openJiuwen `auto_research` 的实验闭环；也支持导入团队自有结果 |
| 能力 | `tyche/analysis/` | 统计量、配对比较、天花板与地板效应、允许数字登记表、表格与图 |
| 能力 | `tyche/paper/` | 章节契约、上下文装配、写作、确定性清洗、ICLR 模板组装与编译、声明生成 |
| 能力 | `tyche/gates/checks.py` | 编译、数字、引用、结构、占位符、内部术语门禁 |
| 能力 | `tyche/review/` | 三位视角评审加忠实度审计、发现台账、修订接受检验 |
| 能力 | `tyche/evolution/playbook.py` | 跨运行写作经验的提炼、晋升、淘汰与导出 |
| 能力 | `tyche/memory/` | 带来源、作用域与更正链的科研记忆；按预算装配每次调用的上下文 |
| 基础 | `tyche/llm.py`、`tyche/cache.py` | 通过 openJiuwen 的 `init_model` 接入 OpenAI 兼容服务；逐次记录 token、缓存命中与时延；提示缓存适配；瞬时网络错误退避重试 |
| 证据 | `tyche/trace/` | 论断–证据地图、逐轮修订差异、产物谱系、环境快照、`tyche verify` |

## 3. 智能体架构：借鉴 Claude Code 与 Codex

Tyche 自己的规划、写作与评审默认以智能体会话运行，工作方式借鉴 Claude Code 与 Codex 这类编码智能体（只借鉴理念，不复制代码与提示词）：模型通过工具行动，工具结果作为下一条消息返回，直到任务完成。写论文和写代码一样，改完先检查，检查不过就不能结束。实验阶段的设计、编码与执行仍由 openJiuwen 的 DeepAgent 完成（第 4 节 S2）。

```mermaid
flowchart LR
    M["模型<br/>(一段只追加的对话)"] -->|工具调用| P{"权限模式<br/>read_only / workspace_write / full"}
    P -->|拒绝| R
    P -->|允许| T["确定性工具<br/>读 · 改 · 查 · 编译 · 委派"]
    T --> H["编辑后检查<br/>清洗 + 该节门禁"] --> R["工具结果块"] --> M
    M -->|不再调用工具| S{"结束前检查<br/>编译 + 全部门禁"}
    S -->|仍有问题，退回| M
    S -->|通过| D[任务完成]
    T -.->|delegate| C["子智能体<br/>全新上下文，只读"]
    M -.->|接近上下文上限| K["压缩：工作摘要 +<br/>当前状态 + 任务"]
```

| 机制 | 作用 |
|---|---|
| 工具协议 | `<call tool=…><arg name=…>原文</arg></call>`，LaTeX 原样传递、无需转义；非文本参数用 pydantic 校验，错误返回给模型 |
| 权限模式 | 按工具作用放行；另有 allow / deny / ask 名单。作者 `workspace_write`，评审、审计员与事实核查员 `read_only`，规划智能体 `read_only` 加文献检索 |
| 待办清单 | 智能体自己维护，宿主在每批结果后重申，工作台实时显示 |
| 结束前检查 | 作者结束时宿主编译论文并跑全部门禁，有问题就退回，最多 `agents.max_stop_blocks` 次 |
| 子智能体 | 事实核查员与每位评审各自在全新上下文中工作，只返回结论或报告 |
| 上下文压缩 | 接近上下文窗口时写工作摘要并开启新对话，而不是截断 |
| 回滚与转录 | 被拒绝的修订把对话截断回检查点；每个会话写 JSONL 转录，存为 `agent_transcripts` 产物 |

| 智能体 | 阶段 | 工具 | 完成条件 |
|---|---|---|---|
| 规划智能体 | S0 | 回顾经验、文献检索（至多 4 次）、校验计划、提交计划 | 提交的计划通过模式校验与机械检查 |
| 作者智能体 | S4、S5 | 读 / 写 / 精确编辑章节、设标题、查允许数字、检索证据、读实验设计与反思、lint、编译、回复发现、委派事实核查 | 写作：七节齐全、有标题、编译通过、无 blocker 与 major；修订：每条发现已回复、无 blocker、无新增 major |
| 事实核查员 | S4、S5 | 读章节、查允许数字、检索证据、读实验设计与反思 | 返回问题清单 |
| 评审 ×3、审计员 | S5 | 读章节、查允许数字、检索证据、提交报告 | 报告通过 `ReviewOutput` / `AuditOutput` 校验 |

没有任何工具能登记数字、加入参考文献或让门禁通过，所以证据边界与第 1 节完全相同。所有工具、钩子与检查都有离线测试；离线自检让脚本化的智能体通过真实工具完成全部阶段。`agents.enabled: false` 恢复逐节单次调用的写作与单次调用的评审。

## 4. 阶段数据流

```mermaid
flowchart LR
    T[题目 + 方向预设] --> S0[S0 规划] --> S1[S1 文献] --> S2[S2 实验] --> S3[S3 分析] --> S4[S4 写作] --> S5[S5 评审修订] --> S6[S6 演进] --> S7[S7 打包]
```

| 阶段 | 主要输入 | 主要产物 | 停止条件 |
|---|---|---|---|
| S0 规划 | 题目、方向预设、生效的写作经验、人工备注 | `plan`（经 pydantic 校验的 JSON）、规划智能体转录 | 智能体未提交有效计划（或 3 次校验失败） |
| S1 文献 | 计划、方向种子查询与经典工作名 | `refs.bib`（只含核验通过的记录）、`source_manifest`、`research_summary` | 检索为空；核验通过的论文过少；综述主题落不到检索到的论文上 |
| S2 实验 | 计划、调研综述 | `experiment_results/<variant>.metrics.json`（含逐条目结果）、实验设计、生成代码、反思记录 | 成功变体少于 2 个；调用失败的条目比例超过 `experiments.max_failed_item_rate`（默认 1%） |
| S3 分析 | 指标文件、计划 | `analysis`、`numbers`（允许数字登记表）、主结果表、配对表、柱状图 | 指标文件无法比较（统计代码报错） |
| S4 写作 | 计划、结果简报、允许的引用、证据卡、可用标签 | 七个章节与标题（初稿）、作者会话状态与转录、上下文装配清单 | 作者智能体用完轮次仍有章节未写 |
| S5 评审 | 初稿、作者会话、未被引用的相关论文 | 逐轮构建（编译、LaTeX 修复、超页压缩、门禁）、评审分数、发现台账、评审与作者转录、最佳稿 | 达到目标分、连续无进步或轮数上限时结束 |
| S6 演进 | 台账 | 写作经验（candidate / active / retired）、`evolutions.json` | — |
| S7 打包 | 评审阶段记录的 PDF、源码与门禁结果 | `paper.pdf`、`paper_source/`、`run_record/`、`provenance.json`、`claims.json`、`environment.json`、`run_report.md` | 门禁有阻断项 |

## 5. 运行目录与交付包

每次运行位于 `workspace/runs/<run-id>/`。所有产物都以不可变版本保存，同一产物再次保存时生成新版本。`provenance.jsonl` 为每个版本记录路径、SHA-256、产生阶段、输入与父版本，`usage.jsonl` 为每次模型调用记录阶段、用途、token 数、缓存命中与时延，`events.jsonl` 记录阶段开始与结束、评审轮次、引用增补等事件。

打包目录是自包含的：它带有全部产物版本、运行配置（不含密钥）、事件与用量日志。`tyche verify <打包目录>` 只用这些文件重新执行以下检查，不需要网络，也不调用模型：

1. 重算全部哈希；
2. 用打包的指标文件重算统计量与允许数字登记表，并逐字节比对；
3. 用数字门禁检查正文中的每个数字；
4. 核对每个引用都来自已核验记录；
5. 重建论断–证据地图并比对。

## 6. 可靠性设计

- **续跑与重跑**：`--resume` 从第一个未完成阶段继续；`--from-stage X` 重置 X 及其后续阶段。重跑调研、分析或规划时，本运行此前写入记忆的同类条目先被标记失效。
- **实验尝试隔离**：openJiuwen 的每次实验尝试使用新的 manager run id（`tyche-<run>-a<N>`），被中断的尝试原地续跑；设计修订后遗留在 `results/` 中的旧变体不会被收集。
- **瞬时错误重试**：连接中断、超时、429 与 5xx 按 5、20、60、120 秒退避重试，其他错误直接暴露。
- **修订回滚**：候选稿必须编译成功，阻断项不增加，不出现新的重大门禁问题，综合分下降不超过容差，否则回滚到上一稿。整个过程始终保留最佳稿。
- **并发保护**：`tyche run` 对每个运行持有排他锁，工作台在同一把锁内检查并启动运行，同一运行不会被两个进程同时推进。

## 7. 安全与合规

- **密钥**：只来自环境变量或被 git 忽略的 `.env`。配置文件只记录环境变量名，日志与产物中的模型描述不含密钥（`ModelSpec.public_dict()`）。
- **不可信文本**：检索到的论文摘要与网页内容经 `sanitize_untrusted` 处理，放在带分隔符的提示块中，只作为数据使用。
- **Web 工作台**：默认只监听 127.0.0.1，并校验 Host 与 Origin。绑定其他地址必须显式 `--allow-remote`，这时使用每次启动生成的访问令牌。`.env` 中的密钥只写不读。
- **自检夹具**：离线自检使用明显虚构的数据（arXiv 编号以 `0000.` 开头，作者为 Fixture / Testcase），不会进入真实论文。
- **上游边界**：不修改 openJiuwen；JiuwenSwarm 上游文件只在打包集成需要时做最小改动，并在提交信息中说明（见 `NOTICE.md`）。
