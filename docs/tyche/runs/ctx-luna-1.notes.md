Operator notes for the planner:
- The subject model the experiments call is strong (gpt-6-luna). Design the task so that the context policy matters:
  the raw agent trace (tool outputs, observations, instructions) must exceed the per-step prompt-token budget, so no
  variant can simply pass the whole trace.
- Avoid ceiling and floor effects: calibrate task difficulty in a small pilot so that no variant is near 100% or near 0%,
  and use the same tasks, seeds, budgets, and model settings for every variant.
- Place the decisive evidence at controlled depths and mix it with long, partly irrelevant tool outputs, so losses from
  truncation or summarisation can be separated from other errors.
- Keep the experiment small enough for a five-page paper: one proposed method, at most three competitive baselines.
