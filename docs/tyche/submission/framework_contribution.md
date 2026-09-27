# openJiuwen 框架贡献说明

Tyche 是 openJiuwen JiuwenSwarm 的 Apache-2.0 fork。openJiuwen agent-core（`openjiuwen`）固定在锁定提交 `9e3390195a9ea15235b2b5f7412cb2aa440622cc`，Tyche 只调用其公开模块，不修改其源码。本文说明两部分内容：一是 Tyche 为 JiuwenSwarm / openJiuwen 生态新增的能力，二是在真实运行中发现的 openJiuwen 问题、Tyche 侧的处理方法，以及建议的上游改动。

## 1. 功能拓展

以下代码都在本仓库中实现，以 Apache-2.0 发布，可直接复用。

1. **科研论文蜂群技能 `tyche-iclr-paper`**（`jiuwenswarm/resources/agent/workspace/skills/tyche-iclr-paper/`）：用 SwarmFlow 编排 8 个阶段，每个阶段智能体只执行对应的确定性命令并回报结构化状态；研究计划可以通过 `human()` 人工审批。该技能通过了 JiuwenSwarm `swarmskill-creator` 校验器。
2. **Agent 模式技能 `tyche-paper`**：在 JiuwenSwarm 对话中以单智能体方式调用同一流水线。
3. **auto_research 科学闭环的宿主适配层**（`tyche/experiments/bridge.py`）：
   - 只开启设计、编码、执行、反思四个模块，用上层应用自己的研究输入替代网页调研；
   - 每次尝试使用独立的 manager run id，被中断的尝试原地续跑；
   - 只收集最近一次执行中成功完成的变体；
   - 从 openJiuwen 自己的 `agent_trace.jsonl` 汇总各智能体的调用与 token 用量，并连同轨迹一起存入运行记录。

   任何需要复用 openJiuwen 实验能力、但自行撰写论文或报告的应用都可以直接使用这一层。
4. **与 `agent_evolving` 互通的写作经验演进**（`tyche/evolution/playbook.py`）：评审发现被提炼成写作经验，经过门控后才晋升，并以 `EvolutionLog / EvolutionRecord` 格式导出为技能的 `evolutions.json`。导出时保留 JiuwenSwarm 或人工添加的其他演进记录。
5. **证据约束的论文生成与离线核验**（`tyche verify`）：参考文献只来自核验过的学术 API，结果数字只来自统计代码。打包目录中的每个数字与引用都可以离线重算和核对，为基于 openJiuwen 的科研智能体提供了可审计的交付格式。
6. **证据约束的智能体运行时**（`tyche/agent/`）：借鉴 Claude Code 与 Codex 的工作方式，运行在 openJiuwen `init_model` 创建的任意模型上：
   - 文本工具协议，LaTeX 等长文本参数无需 JSON 转义；
   - 按工具作用划分的权限模式与 allow / deny / ask 名单；
   - 智能体维护的待办清单，编辑后检查，以及宿主检查不通过就退回任务的结束前检查；
   - 全新上下文的子智能体、长对话压缩、截断式回滚与 JSONL 转录；
   - 每个会话都是只追加的对话，服务端提示缓存覆盖此前所有轮次。

   工具全部是宿主代码，应用只需提供自己的工具与检查。Tyche 用它实现规划、作者与评审智能体。
7. **提示缓存适配与用量计量**（`tyche/cache.py`、`tyche/llm.py`）：
   - 在 openJiuwen `init_model` 之上按服务类型附加缓存提示；
   - 逐次记录输入、缓存命中与输出 token；
   - 连接中断、超时、429 与 5xx 自动退避重试；
   - 服务端拒绝缓存参数时退回普通请求。

## 2. openJiuwen 问题与建议的上游改动

以下问题都是在使用锁定提交真实运行 auto_research 时遇到的。Tyche 用子类、公开参数或调用方代码绕开了它们，没有修改 openJiuwen。

| # | 问题 | 现象 | Tyche 的处理（位置） | 建议的上游改动 |
|---|---|---|---|---|
| 1 | 编码智能体的 ReAct 轮次上限不可配置 | `harness.subagents.create_code_agent` 默认每次调用 15 轮，`CodeImplementationAgent` 不透传该参数；一个验证周期常在 `run.py` 写出前就耗尽轮次 | 构建编码智能体时，用工厂函数的 `max_iterations` 参数把上限设为 `experiments.code_agent_max_iterations`（默认 80）（`code_implementation_agent`） | 在 `CodeImplementationAgent` 构造参数或 `pipeline` 配置中暴露 `max_iterations` |
| 2 | 设计修订后编码轮可能空转 | 智能体只读取旧代码就结束回合，旧实现原样通过验证，修订后的设计没有被实现 | 比较本轮前后的源码摘要，未变化时附上明确的宿主指令重跑一次（`TycheCodeImplementationAgent._run_async`） | 在 code_implementation 的验证环节检测“设计已变、代码未变”，重试或向 manager 报告 |
| 3 | “Read First” 输入在沙箱外 | 设计智能体给编码智能体的指令引用了项目相对路径（`inputs/…`、`experiments/<run>/manager/…`），编码智能体的文件工具只能访问 `agent_workspace`，读取被拒并浪费轮次 | 把这些文件镜像到沙箱内的相同相对路径（`mirror_read_first_inputs`） | 在沙箱中只读挂载指令引用的输入，或在指令中改写为沙箱内路径 |
| 4 | pip 安装缺少 SDK 参考文档 | `openjiuwen_reference_rail` 从 `<site-packages>/docs` 读取参考文档，但 wheel 不包含 `docs/`；缺失时编码智能体得不到 SDK 参考，且没有任何提示 | 安装脚本获取锁定提交的 `docs/`（`scripts/tyche/fetch_openjiuwen_docs.sh`），`tyche doctor` 检查文档是否存在 | 把参考文档作为 package data 发布，或在文档缺失时显式告警 |
| 5 | 智能体用量没有汇总接口 | `ObservabilityRail` 把每次调用的用量写在分散的 `agent_trace.jsonl` 中，`ManagerRuntime.arun` 返回的终止报告不含 token 汇总，调用方难以核算实验成本 | 汇总轨迹中的 `model_call_end` 事件，按模块统计调用、输入、缓存命中与输出 token（`openjiuwen_usage`），存为 `experiment_usage` 产物 | 在 `TerminalReport` 中返回按模块汇总的用量，或提供读取轨迹用量的公开函数 |
| 6 | 设计修订后结果目录残留旧变体 | 修订删除某个变体后，其 `results/*.metrics.json` 仍留在结果目录，调用方可能误收 | 只收集 `latest_execution` 中 `process_status == "completed"` 的变体，并在说明中列出被忽略的旧变体（`OpenJiuwenEngine.run`） | 新一轮执行前归档旧结果，或在结果目录中写明当前变体清单 |
| 7 | 实验预算约束只是软约束 | 在高推理强度模型上，实验智能体曾设计出远超预算的实验（20 个种子 × 16 个回合 × 4 个变体，外加校准与探测），单次运行的调用上限达 16,000 次 | 在 `experiments.constraints` 中写明“硬上限：每个变体至多 600 次、总计 3,000 次模型调用（包括冒烟测试、试点、校准与探测）” | 在 manager 的计划审查中加入对调用预算的结构化检查 |

## 3. PR 信息

**本项目仓库**：<https://github.com/sweetcornna/Tyche>（公开，Apache-2.0）

| PR | 内容 | 状态 |
|---|---|---|
| [sweetcornna/Tyche#8](https://github.com/sweetcornna/Tyche/pull/8) | 以 JiuwenSwarm fork 为基础，加入 ICLR 短论文智能体 Tyche | 已合并（2026-09-25） |
| [sweetcornna/Tyche#9](https://github.com/sweetcornna/Tyche/pull/9) | 在 DeepSeek V4.1 Flash 上端到端运行，加强实验完整性检查 | 已合并（2026-09-26） |
| [sweetcornna/Tyche#10](https://github.com/sweetcornna/Tyche/pull/10) | 面向所有服务的提示缓存：只追加的多轮对话与服务端缓存适配；结果表格排版 | 已合并（2026-09-26） |
| [sweetcornna/Tyche#11](https://github.com/sweetcornna/Tyche/pull/11) | 收尾：科研工作台、打包目录离线核验、评审与分析修正、gpt-6-luna 运行、提交包生成 | 审阅中 |

**上游 openJiuwen**：第 2 节的问题尚未向 openJiuwen agent-core 仓库提交 Issue 或 PR；提交后在此补充链接。

## 4. 兼容性说明

- 不修改 openJiuwen 源码。所有适配都通过公开构造参数、子类重写或调用方代码完成，并随锁定提交一起测试。
- JiuwenSwarm 上游文件中，只有 `pyproject.toml` 为打包 `tyche` 包、控制台脚本与包数据做了改动，每次改动都在提交信息中说明（见 `NOTICE.md`）。
- 两个技能放在 JiuwenSwarm 的技能目录下，与其他技能并列，不影响上游已有技能与服务。
