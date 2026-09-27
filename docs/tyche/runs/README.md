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

<!-- Filled in from each run's package/run_report.md and analysis once the run is packaged. -->
