Operator notes for the planner:
- The subject model the experiments call is strong (gpt-6-luna). Design the task so that the memory policy matters:
  the interaction history must exceed the per-query prompt-token budget, so no variant can simply read the full history.
- Avoid ceiling and floor effects: calibrate task difficulty in a small pilot so that no variant is near 100% or near 0%,
  and use the same tasks, seeds, budgets, and model settings for every variant.
- Include fact updates and retractions interleaved with distractor facts, and questions that need the latest valid fact,
  so stale answers can be counted separately from other errors.
- Keep the experiment small enough for a five-page paper: one proposed method, at most three competitive baselines.
