# 示例运行 / Example runs

三个示例运行分别对应赛题的三个建议方向，全部使用 `gpt-6-luna`（`reasoning_effort: max`，配置见
[../configs/reasoning-max.yaml](../configs/reasoning-max.yaml)），规划前给出下列研究备注（`--notes`），规划后人工检查计划再继续。

| 运行 | 方向 | 题目 | 研究备注 |
|---|---|---|---|
| `mem-luna-1` | `memory_engine` | Supersession-aware agent memory: do provenance-tagged correction chains reduce stale-fact answers under a fixed prompt-token budget? | [mem-luna-1.notes.md](mem-luna-1.notes.md) |
| `ctx-luna-1` | `context_engineering` | Provenance- and priority-aware context packing: does budgeted packing of tool outputs preserve decisive evidence better than truncation and rolling summaries? | [ctx-luna-1.notes.md](ctx-luna-1.notes.md) |
| `evo-luna-1` | `self_evolution` | Gated lesson promotion for self-evolving agents: must a distilled lesson show a verified gain before it enters the prompt? | [evo-luna-1.notes.md](evo-luna-1.notes.md) |

复现命令见 [../REPRODUCE.md](../REPRODUCE.md#4-复现示例运行)。运行目录（`workspace/runs/<run-id>/`）不纳入版本库；
打包后的 `package/` 目录包含论文、LaTeX 源码、完整运行记录、论断–证据地图、环境快照与溯源清单。

## 结果

下表数字全部取自各运行打包目录中的 `run_report.md` 与分析产物（`run_record/artifacts/analysis/`），可用 `tyche verify workspace/runs/<run-id>/package` 离线核验。

### `mem-luna-1`（记忆引擎）：已打包，`tyche verify` 全部通过

- 题目：*SCOPE Supersession Chains Add Prompt Cost Without Reducing Stale Answers in Synthetic Fact Streams*
- 门禁通过；正文 5 页；14 篇不同引用（其中 5 篇由评审阶段请求、经同一核验器接纳）；论断–证据地图 54 条论断（50 已核验、4 支撑较弱、0 未核验），147/147 个数字匹配计算值。
- 评审：综合分 5.238（初稿）→ 5.381（第 1 轮）→ 5.476（第 2 轮）；第 3 轮修订降至 4.952，被拒绝并回退。
- 结论（负结果，论文如实报告）：提出的方法 SCOPE 与去掉链接的时间戳检索、最新状态存储都达到 1.00 精确匹配率与 0.000 过期答案率，形成天花板，实验无法区分三者；SCOPE 比时间戳检索平均多用 26.1 个提示 token（95% CI 23.6 至 28.6）。相对 recency-aware BM25，精确匹配率高 0.067（95% CI 0.039 至 0.098，p < 0.001），过期答案率差 −0.021 不显著（95% CI −0.049 至 0.000，p = 0.245）。论文的局限部分明确指出了天花板效应。
- 模型用量：101 次调用，输入 1,627,026 token（其中 1,268,736 命中提示缓存，命中率 0.78），输出 308,344 token。

这个运行暴露的实验设计问题（任务太容易）促成了默认配置中新增的难度校准约束：先用小规模试跑确认主指标没有变体处于 0 或 1 的边界，再跑正式实验。

### `ctx-luna-1`（上下文工程）

运行中。

### `evo-luna-1`（自我演进）：实验阶段受阻，未生成论文

openJiuwen 实验智能体设计的方案需要先对 4 个变体做校准试跑并冻结统一的 token 上限，每个变体的请求上限设为 16,000 次，远超配置约束中“每个变体约 600 次模型调用”的预算；中断后恢复时，openJiuwen 的 manager 以 `manager_blocked`（缺少冻结的校准输出）结束。按照证据边界，Tyche 在没有实验结果时不会写论文，该阶段记录为失败。重新运行（`tyche run --resume --run-id evo-luna-1` 会从失败的实验阶段继续，并因上一次尝试已终止而新开一次 openJiuwen 尝试）需要数小时的模型调用。
