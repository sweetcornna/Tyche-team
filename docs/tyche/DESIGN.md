# Tyche 设计说明

本文说明 Tyche 各阶段的输入、输出与判定规则，便于复现审核与答辩。代码位置均相对仓库根目录。

## 1. 设计目标

1. **结果可追溯**：论文中的文献、数字、图表都能追溯到检索记录、实验日志与统计脚本。
2. **失败要显式**：证据不足时停止并说明原因，而不是生成“看起来合理”的内容。
3. **分数导向但不作弊**：以 Stanford Agentic Reviewer 公开的 7 个评审维度组织自评与修订，但只通过改写提高清晰度、证据支撑与定位，不伪造实验。
4. **复用 openJiuwen 能力**：实验自动化、模型接入、上下文压缩与技能演进格式都来自 JiuwenSwarm / agent-core，Tyche 只补齐它们缺少的环节。
5. **像编码智能体一样工作**：规划、写作与评审借鉴 Claude Code 与 Codex 的工作方式，由模型通过工具循环完成任务，改完先检查、检查不过不能结束（见第 3 节）。只借鉴理念，不复制它们的代码与提示词。

## 2. 运行目录与溯源

`workspace/runs/<run-id>/` 下：

| 路径 | 内容 |
|---|---|
| `state.json` | 各阶段状态（pending/running/done/failed）、题目、方向、配置摘要 |
| `events.jsonl` | 追加式事件日志（阶段开始/结束、产物保存、评审轮次、引用增补等） |
| `provenance.jsonl` | 每个产物版本一行：名称、版本、路径、SHA-256、产生阶段、输入、父版本 |
| `artifacts/<name>/v<N>.*` | 不可变的产物版本；重复保存生成新版本 |
| `usage.jsonl` | 每次模型调用的阶段、用途、token 数与时延 |
| `config.json` | 本次运行的完整解析配置（不含密钥），`--resume` 时沿用 |
| `write/context_manifests/`、`review/context_manifests/` | 写作与修订调用的上下文装配清单（纳入/截断/丢弃的块及 token 数、引用的记忆条目），每次重跑该阶段时清空重建 |
| `plan/agents/`、`write/agents/`、`review/agents/` | 智能体会话的转录（`transcripts/*.jsonl`：任务、回复、工具调用与结果、检查退回、压缩摘要）与作者自检用的临时构建；转录另存为 `agent_transcripts` 产物 |
| `review/` | 每轮构建目录、评审 JSON、台账、轮次记录 |
| `package/` | 最终交付物 |

`tyche run --resume` 从第一个未完成阶段继续；`--stage X` 重跑某一阶段，并把其后所有阶段重置为待运行。重跑调研、分析或规划时，本运行此前写入记忆的同类条目会先被标记为失效，不会进入之后的提示词。实验引擎每次尝试使用新的 manager run id，只收集最新一次执行中成功的变体。打包时重新计算全部产物的哈希，任何改动都会记录在 `provenance.json` 的 `drifted_artifacts` 中。

## 3. 智能体运行时（`tyche/agent/`）

`agents.enabled: true`（默认）时，Tyche 自己的规划、写作与评审以智能体会话运行，工作方式借鉴 Claude Code 与 Codex：模型通过工具行动，工具结果作为下一条消息返回，直到任务完成。每个工具都是确定性的宿主代码，证据边界不变：没有任何工具能登记数字、加入参考文献或让门禁通过。`agents.enabled: false` 恢复逐节单次调用的写作与单次调用的评审，两条路径共用同一套门禁、评审台账、接受测试与回滚。

| 机制 | Tyche 的实现 | 借鉴的理念 |
|---|---|---|
| 工具循环 | `AgentSession.run`：回复中的工具调用按顺序执行，结果以 `<result>` 块作为下一条消息返回；不含调用的回复表示本轮结束 | 智能体循环 |
| 工具协议 | `<call tool="…"><arg name="…">原文</arg></call>`。文本参数原样传递，LaTeX 不需要 JSON 转义；其他参数写成 JSON，由 pydantic 校验，错误返回给模型 | 工具调用与参数校验；Codex 用自由文本格式传补丁 |
| 权限模式 | 按工具作用（read / check / edit / external / delegate / result）放行：`read_only`、`workspace_write`、`full`，另有 allow / deny / ask 名单与审批回调。不允许的工具不出现在工具说明中，调用会被拒绝并说明原因 | Claude Code 的权限模式；Codex 的沙箱与审批策略 |
| 待办清单 | `update_todos` 整体替换清单，同一时间最多一项进行中；宿主在每批工具结果后、压缩后重申清单，工作台实时显示 | TodoWrite、update_plan |
| 编辑后检查 | `write_section` / `edit_section` 先做确定性清洗，再立即对该节运行所有不需编译的门禁（数字、引用、结构、占位符、内部术语），结果随工具结果返回 | 编辑后的诊断反馈 |
| 精确编辑 | `edit_section` 要求原文在该节中唯一出现；找不到时返回最接近的一行 | 精确字符串替换 |
| 结束前检查 | `on_stop` 钩子：作者要结束时，宿主编译论文并运行全部门禁，仍有问题就把问题退回，最多退回 `agents.max_stop_blocks` 次 | Stop 钩子；改完先跑测试 |
| 子智能体 | `delegate` 把任务交给在全新上下文中运行、只有只读工具的助手（事实核查员），只返回它的答案；每位评审与审计员也是独立会话 | 子智能体 |
| 上下文压缩 | 历史达到上下文窗口的 `agents.compact_at` 时，先让模型写工作摘要，再以摘要、当前论文状态与任务开启新对话，而不是截断 | 对话压缩 |
| 回滚 | 检查点记录对话长度与待办清单；被拒绝的修订把对话截断回检查点，剩余部分仍是已缓存的前缀 | 会话回退 |
| 转录 | 每个会话的任务、回复、调用、结果、退回与压缩写入 JSONL，关键事件（`agent.*`）写入事件日志 | 会话记录 |

一个会话就是一段只追加的对话（`tyche.llm.Conversation`）：系统提示依次是角色说明、工具协议、工具说明与共享上下文，整个阶段内不变；后续任务在同一对话上追加，所以服务端的提示缓存覆盖此前所有轮次。

三类智能体：

- **规划智能体**（S0，`PlannerAgent`）：只读模式，外加文献检索。它可以回顾既往经验（`recall_lessons`），做至多 `agents.planner_searches` 次检索（`search_literature`，结果是不可信数据，只用于判断新颖性和挑选基线，不产生引用），用 `check_plan` 校验草案，最后 `submit_plan`。计划先经 pydantic 校验，再做机械检查：方法与基线重名或变体数超过 `experiments.max_variants` 为错误，拒绝提交；假设未提到任何指标等为警告。
- **作者智能体**（S4/S5，`AgentAuthor`）：`workspace_write` 模式。工具包括读写与精确编辑章节、设置标题、查询允许数字（`lookup_numbers`）、检索证据（`search_evidence`）、阅读完整实验设计与反思、lint、编译（`build_paper`）、回复评审发现，以及委派事实核查员。写作阶段一个任务写完全文：宿主预置按写作顺序的待办清单，结束前检查要求七节齐全、已设标题、编译通过且没有 blocker 与 major 门禁问题。评审阶段每轮一个任务处理全部选中的发现：每条都要回复 fixed 或 rebutted，结束前检查要求没有 blocker，也不能引入新的 major 问题（否则修订循环会拒绝该轮）。编译修复与篇幅压缩也作为任务交给同一会话。它实现了与 `SectionWriter` 相同的接口，所以组装、门禁、评审循环与接受测试不变。
- **评审智能体**（S5）：每位评审和审计员都是只读会话。论文全文在上下文中；它们可以读章节 LaTeX、查允许数字、检索被引论文的证据，核对之后再调用 `submit` 提交报告。报告按 `ReviewOutput` / `AuditOutput` 校验，不通过就退回修改。所有评审与审计员共用同一系统提示与工具说明，论文只需缓存一次；视角在任务消息中。会话没有交出有效报告时，退回到一次普通调用，不会丢掉这位评审。

## 4. 各阶段

### S0 规划（`tyche/planning.py`）

输入为题目、方向预设（`tyche/configs/directions/*.yaml`）、记忆中已生效的写作经验以及可选的人工备注。输出 `ResearchPlan`：研究问题（1–3 个）、假设及可测预测、方法名与机制、基线、实验族、任务、指标、贡献、范围限制、检索式。智能体模式下由规划智能体完成（第 3 节）；否则一次调用，输出经 pydantic 校验，失败时带着校验错误重问，最多 3 次。

### S1 文献调研（`tyche/literature/`）

1. 模型基于计划与方向种子查询生成检索式，并与计划中的检索式合并去重（最多 `literature.max_queries` 条）。
2. 对 arXiv（Atom API）、Semantic Scholar Graph API、OpenAlex 逐一检索。按主机限速，429/5xx 指数退避重试，响应缓存到 SQLite。
3. 方向预设中的经典工作名通过标题检索解析，标题相似度 ≥ 0.88 才接受。
4. 按 arXiv 编号、DOI、S2 编号、规范化标题去重合并；以 BM25（标题加权）加引用数与时效先验做预排序。
5. 模型逐批阅读标题与摘要，给出 0–3 相关度与角色（baseline/mechanism/benchmark/analysis/background）。
6. 对前几篇论文沿 S2 引文图向前、向后各扩展一跳，新候选同样筛选。
7. **核验**：需具备标题、作者、年份与至少一个持久标识；非 arXiv 来源的 arXiv 编号回查 arXiv，DOI 回查 Crossref；标题不符即判定矛盾并排除。
8. **证据卡**：模型为每篇论文写 1–2 条观点，每条必须附摘要中的逐字引文（≥ 20 字符），代码逐字比对，不符即丢弃。
9. 模型把已核验论文归纳为 2–4 个主题，并写出研究空白；主题中的论文编号若不在集合内会被剔除。

输出 `refs.bib`（只含核验通过的记录）、`research_summary.md`（含 auto_research 可解析的 `## Short Summary / ## Key Findings / ## Open Problems`）、`source-manifest.json`、`candidate-pool.json`。

### S2 实验（`tyche/experiments/bridge.py`）

默认引擎调用 openJiuwen `auto_research` 的 `ManagerRuntime`，模块开关为：`topic_survey=false`、`experiment_design / code_implementation / experiment_execution / reflection = true`、`reporting=false`。

- 研究输入：Tyche 的 `research_summary.md` 与研究计划，作为 `research_paths` 传入。
- 约束：短论文规模、至多 4 个变体、记录逐条目结果、禁止硬编码指标。
- 预算：回合数与重试次数更紧。
- 模型：生成的实验代码通过环境变量 `API_KEY / API_BASE / MODEL_NAME` 调用同一模型。

收集的产物包括各变体的 `results/*.metrics.json`、实验设计文档、生成代码与反思记录。openJiuwen 的 ObservabilityRail 为实验智能体的每次模型调用写下 `agent_trace.jsonl`，Tyche 把本次尝试的轨迹存为 `experiment_traces`，并按模块汇总调用次数、输入、缓存命中与输出 token，存为 `experiment_usage`。无论尝试成功与否都会保存，失败的尝试同样消耗了 token。运行报告与资源报告据此统计实验阶段的用量，同一尝试续跑后只计最新一份，不重复累加。

每次尝试都记录其输入摘要（计划、综述、目标与约束）。被中断的尝试只有在输入未变时才原地续跑；重新规划之后会新开尝试。操作者可以用 `--experiment-followup` 给实验智能体一条指令，这条指令通过 openJiuwen 的续跑引导作用于最近一次尝试（已结束的也会重新打开），并作为 `experiment_followup` 产物记入运行记录。

替代引擎：

- `imported`：读取团队自行产生的 `<variant>.metrics.json` 目录，可附 `design.md` 与 `code/`。
- `fixture`：只供离线自检使用的合成数据。

少于两个成功变体时阶段失败，不会进入写作。

### S3 分析（`tyche/analysis/`）

- **变体识别**：名为 `proposed`、或与方法名匹配、或含 `ours` 的变体被视为提出方法。
- **指标选取**：所有变体共有的数值指标（排除记账字段）。计划里用自然语言描述的指标（如“Exact-match accuracy on the latest value”）按描述中名称部分的词映射到指标文件里的标识符（`exact_match_accuracy`），取最具体的唯一匹配；计划指标排在前面，其余信息量指标其次，所有变体取值相同的指标最后。
- **逐条目统计**：从 `per_question` 中找出支撑某指标的逐条目字段（同名字段、`correct/exact_match` 等布尔别名、去掉 `mean_`/`_rate` 后的字段名）和条目子集：分组字段（`stratum`、`pass`、`phase` 等，指标名点到的取值优先，否则取 `main`/`eval` 等默认取值）、指标名或计划描述点名的布尔标志（如 “on changed-target queries” → `changed_target`）、是否剔除失败调用（`error`/`_fatal`）。**同一条规则必须对所有变体同时复现其报告值**才被采用，避免某个变体的 0 值恰好被错误子集“复现”而导致 n 或置信区间错误。复现先按浮点精度精确比较，只有报告值写成 2–6 位小数时才按四舍五入容差比较。若有多条规则都能复现、但选出的条目集合不同（例如全部为 0 时含不含失败调用都成立），条目集合无法确定：该指标的 n、置信区间与配对检验一律不给出，并在分析说明中注明。没有共同规则时才逐变体各自复现，且只有规则相同的变体之间才做配对比较；仍不能复现的指标只报告点值。随后计算均值、标准差与 95% percentile bootstrap 置信区间（默认 2000 次重采样）。每个区间与 p 值使用由（种子、指标、变体）派生的独立随机数流，因此一个数字不会因为其他指标的增减而改变。
- **配对比较**：按条目编号对齐（优先 `pair_id`，因为 `id` 常带变体名；无编号时按位置对齐；同一条目的重复试验先求均值），计算差值及其 bootstrap 置信区间、sign-flip 置换检验 p 值（默认 5000 次，加一校正）和相对变化。逐条目结果完全相同的比较在结果简报中标为“平局”。
- **天花板/地板效应**：取值为 0/1 的比例指标若有两个及以上变体恰为 0 或 1，分析说明会指出实验无法区分这些变体，写作阶段必须如实表述。
- **方向判定**：名称含 token、cost、latency、error、stale、violation 等词的指标视为越低越好，最优值标注随之调整。
- **允许数字登记表**：登记上述所有数值（含百分比形式），以及实验设计与计划文档中出现的全部设置数字。
- **图表**：生成主结果表、配对比较表与带置信区间的柱状图。

### S4 写作（`tyche/paper/`）

- **写作方式**：智能体模式下由作者智能体在一个会话中写完全文，边写边检查（第 3 节）；否则每节一次调用，章节之间共享同一段只追加的作者对话。
- **写作顺序**：方法 → 实验 → 分析 → 相关工作 → 引言 → 结论 → 摘要，最后是标题。先写实质内容，再写框架性段落（智能体模式下这是预置待办清单的顺序）。
- **章节契约**：每节有目标、硬性要求与字数范围（`paper.sections`，面向 ≤ 5 页的短论文），例如引言以 2–4 条贡献列表结尾、相关工作每个主题一段且引用 ≥ 6 篇、分析必须包含 Limitations 段落、实验必须引用所有表图标签。
- **上下文装配**（`tyche/memory/context_pack.py`）：必选块包括章节契约、研究计划、允许的引用列表、结果简报与可用标签；可选块包括实验设计摘录、调研综述、按检索相关度选取的证据卡、生效的写作经验以及已写章节的摘要。装配在 `memory.context_budgets.section` 预算内进行，可选块按优先级纳入，放不下的截断，清单落盘。
- **确定性清洗**（`sanitize.py`）：去掉模型自带的 `\section`；将 Markdown 转为 LaTeX；替换 Unicode 标点；在正文模式下转义 `% & _ #`（不进入数学、tabular 与标识符参数）；补全未闭合的行内公式；删除不在允许列表中的引用键并记录。
- **组装与编译**：使用 ICLR 2027 官方样式、`natbib` 与 `iclr2027_conference.bst`，由 `latexmk -pdf` 编译。编译错误定位到具体章节文件，交给模型只修 LaTeX 问题（最多 3 次）；主文页数超限时按比例压缩最长的章节（最多 3 次）。主文页数以 “AI use statement” 标题出现的页为界，与 ICLR 的计页口径一致。
- **声明**：AI use statement 与 Reproducibility statement 由代码根据运行元数据生成，包括所用模型、实验引擎、随机种子与人工审阅声明。

### 门禁（`tyche/gates/checks.py`）

| 门禁 | 规则 | 严重度 |
|---|---|---|
| compile | 编译成功；无未定义引用、未定义文献；PDF 中无 `??` | blocker |
| number | 摘要/引言/实验/分析/结论中的每个数字须是登记值按其精度的四舍五入或其百分比形式；带负号的数字须符号一致。跳过标识符参数（`\ref`/`\cite`/`\label` 等）、版面尺寸、上下标与指数、“Table 3/Section 4.2”之类的交叉引用编号、处于年份语境的四位年份，以及 10 以下的正整数；紧贴单位（如 `12.5x`、`13.5ms`）的数字整体检查，不会被截断 | blocker |
| citation | 引用键必须存在于核验后的 bib；“X et al. (年份)” 附近必须有引用命令；相关工作引用篇数达标 | blocker / major |
| structure | 各章节齐全；引言有贡献列表；分析有局限性；所有表图被引用；字数在契约范围内；主文页数不超限 | blocker / major / minor |
| placeholder | 无 TODO/TBD/XXX/`??`/[citation needed] 等残留 | blocker |

### S5 评审与修订（`tyche/review/`）

- **评审团**：三位视角评审（rigor / positioning / clarity），各自按 7 个维度 1–10 分打分，并给出 ICLR 总评、置信度、优缺点与至多 8 条发现。每条发现须带章节、严重度、维度、论文原文逐字引文、问题、可通过改写完成的修改建议与关闭标准。评审只能要求改写，不能要求补做实验；证据不足时应收窄结论。
- **引文校验**：发现中的引文若在论文文本中找不到，严重度降一级；minor 级直接丢弃，以抑制幻觉式批评。
- **定位参照**：评审同时拿到检索到但未被引用的相关论文清单（R01…R15）。若评审点名要求讨论其中某篇，Tyche 先核验该论文，再把它加入 bib 与允许引用列表。
- **忠实度审计**：审计员对照结果简报与被引论文的证据，检查误引、夸大与遗漏的局限，只追溯、不重算。
- **台账**：每条发现有编号与生命周期（open → resolved / wontfix / unaddressed）。重复提出计为 re-flag，超过上限即关闭为 unaddressed。写作者须对每条发现回复 fixed 或 rebutted，下一轮评审逐条裁决。门禁问题以 `gate:*` 来源进入台账，门禁不再报告时自动关闭。
- **修订与接受**：只重写有待处理发现的章节（每轮至多 8 条；智能体模式下作者智能体在一个任务中处理本轮全部发现），重新编译、过门禁、再评审。候选稿须编译成功、阻断项不增加且综合分下降不超过容差，才会被接受，否则回滚。达到目标分、连续无进步或到达轮数上限时停止，始终保留最佳稿。

综合分（composite）是 7 个维度的等权平均，只用于同一论文不同草稿间的比较。

### S6 演进（`tyche/evolution/playbook.py`）

模型把台账提炼为至多 6 条写作经验，每条包含类别、可执行的指导语、适用章节与来源发现编号。经验以 global 作用域存入记忆，状态机如下：

- **candidate**：首次出现。
- **active**：在至少 `promote_after_runs` 次运行中出现，且至少 `promote_after_helped` 条来源发现的修复被接受、分数未降。只有这一状态的经验会进入后续写作上下文。
- **retired**：处于 active 状态时已被注入写作上下文，但同类问题仍在 `retire_after_misses` 次运行中复现，说明指导无效。

生效经验导出为 JiuwenSwarm 技能 `evolutions.json` 格式（复用 `openjiuwen.agent_evolving` 的 `EvolutionLog / EvolutionRecord`），可在 JiuwenSwarm 中查看与回滚。

### S7 打包

打包只使用评审阶段本次运行记录下的 PDF、源码与门禁结果（按产物版本号精确引用），不会取到更早评审运行留下的 PDF。门禁未通过时拒绝打包；`--allow-gate-failures` 可强制打包，此时重新生成注明 UNVERIFIED 的 AI use statement 并重新编译，输出 `paper_UNVERIFIED.pdf`。交付物还包括 `paper_source/`、`run_record/`（全部产物版本、上下文清单、评审轮次、事件/用量日志、运行配置）、`provenance.json`、`review_ledger.json`、`gates.json`、`claims.json`、`environment.json`、`run_report.md`。

### 可追溯层（`tyche/trace/`）

四个视图都由确定性代码从运行目录计算，不调用模型：

- **论断–证据地图**（`claims.py`）：把论文各节 LaTeX 切成句子，挑出含数字或引用的句子。数字用与数字门禁相同的登记表匹配到具体计算值（变体、指标、统计量、配对比较与其指标文件），引用匹配到已核验文献及其证据卡原文。状态规则：有数字无法匹配或引用键未知 → 未核验；引用的文献没有证据卡 → 支撑较弱；否则已核验。由代码生成的 AI use statement 与复现声明不计入。
- **修订历史**（`revisions.py`）：从评审各轮的构建目录恢复每轮的章节文本（仅在与已记录的评审轮次和最终论文产物一致时采用），给出逐节 unified diff、字数变化和该轮处理的台账发现；被拒绝的候选稿也可查看。
- **产物谱系**（`lineage.py`）：溯源记录中每个产物版本的输入与父版本构成的有向图，可查询任一产物的全部上游。
- **环境快照**（`environment.py`）：Python、平台、Tyche 与 openJiuwen 版本及锁定提交、LaTeX/poppler 工具版本、git 状态、各角色模型的公开描述；任何形似密钥的值都会被替换。
- **离线核验**（`verify.py`，`tyche verify`）：只用打包目录重做上述检查：产物哈希、PDF 哈希、由打包的指标文件与计划重算统计量和允许数字登记表并逐字节比对、用数字门禁检查正文、核对引用来源于已核验记录、重建论断地图并比对。`tyche selftest` 对自己的打包目录运行同样的核验。

## 科研工作台（`tyche/web/`）

`tyche ui` 启动只监听本机的 FastAPI 服务并打开浏览器。后端只做三类事：读取运行目录（`runs.py`，纯函数）、启动/停止 `python -m tyche run` 子进程并识别命令行启动的运行（`processes.py`）、读写 `.env` 中白名单内的键（`settings.py`，密钥只写不读）。所有返回内容都来自确定性代码与已有产物，界面不会让模型改写任何证据。安全措施：默认绑定 127.0.0.1，并校验 Host/Origin（防 DNS 重绑定与跨站写请求）；绑定其他地址必须显式 `--allow-remote`，此时每次启动生成访问令牌，经打印的 `?token=` 链接换成 HttpOnly、SameSite=Strict 的 cookie。运行编号在成为路径前校验；请求中的模型名只允许安全字符并以 JSON 字符串传给 `--set`，`.env` 按字面读取（不做 `${VAR}` 展开）并以单引号写回，因此请求无法把一个密钥读进会被记录的设置。停止运行会结束整个进程树（包括离开进程组的实验脚本）；`tyche run` 对每个运行持有排他锁，服务端在同一把按运行的锁内检查与启动。读取正在追加的 JSONL 时只取以换行结束的完整行。实时更新通过 SSE（运行摘要、流水线事件、openJiuwen 实验事件）推送。

前端（`tyche/web/frontend/`，React + TypeScript + Tailwind + Radix）采用桌面聊天应用式布局：侧边栏按日期分组列出运行，主栏把每个阶段渲染为一条可展开的回复，底部输入框在规划审批时用于填写修改意见，右侧可拖拽面板提供论文、计划、文献、实验、结果、评审、论断地图、修订、谱系、报告、产物与日志 12 个视图。规划、写作与评审阶段还显示智能体活动：待办清单、最近的工具调用、编译结果与检查退回。支持中英文、明暗主题、手机布局与键盘快捷键。

## 5. 与 JiuwenSwarm 的集成

- **模型**：`tyche/llm.py` 通过 `openjiuwen.core.foundation.llm.init_model` 接入，支持 JiuwenSwarm 支持的所有 OpenAI 兼容服务。
- **实验**：直接驱动 openJiuwen 的 `ManagerRuntime`，方式与 JiuwenSwarm 的 RSI paper provider 相同，但关闭了调研与报告模块。
- **蜂群编排**：技能 `tyche-iclr-paper` 以 SwarmFlow 脚本按阶段编排，每个阶段智能体只执行对应命令并汇报状态，支持 `human()` 人工审批计划。该技能通过了 JiuwenSwarm `swarmskill-creator` 的校验器。
- **Agent 模式**：技能 `tyche-paper` 提供对话式入口。
- **技能演进**：生效经验以 `evolutions.json` 格式导出。

## 6. 已知限制

- 自动实验的成败取决于 openJiuwen 实验智能体与所用模型的能力。遇到失败时，可以用 `--engine imported` 接入团队自己的实验。
- 评审团与 paperreview.ai 的评分模型不同。它能指出薄弱维度，但不能预测最终分数。
- 默认模型（如 DeepSeek）为纯文本模型，评审基于 PDF 抽取的文本与表格，不评价图像的视觉质量。
- 本仓库的离线测试不访问网络与真实模型；真实运行需要可访问的模型 API 与学术 API。
