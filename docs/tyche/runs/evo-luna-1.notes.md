Operator notes for the planner:
- The subject model the experiments call is strong (gpt-6-luna). Design the task so that the evolution policy matters:
  tasks should have a learnable, checkable regularity (for example a hidden house rule or tool convention) that the
  agent can only discover from feedback on earlier episodes, and lessons should cost prompt tokens.
- Avoid ceiling and floor effects: calibrate task difficulty in a small pilot so that no variant is near 100% or near 0%,
  and use the same task sequences, seeds, budgets, and model settings for every variant.
- Include harmful or overfitted lessons (for example after a distribution shift) so regressions can be measured,
  not only gains.
- Keep the experiment small enough for a five-page paper: one proposed method, at most three competitive baselines.
