---
name: simulator-verdict-failure-analysis
description: Separates simulator-authoritative evaluation from read-only video-first failure diagnosis with selectable time intervals and evidence-linked hypotheses.
---

# Simulator Verdict and Failure Analysis

Use this policy at the end of every simulator manipulation run.

## Action phase

- Do not decide or state that the task succeeded or failed. Model observations are
  evidence, not the benchmark verdict.
- After acting, record the visible effect and uncertainty, then end with
  `evaluation_requested`.
- The supervisor submits RoboEnv's native evaluator. Only that recorded verdict is
  the task label.

## Failure-analysis phase

Run this phase only after the native evaluator returns failure. The episode is
terminal and frozen; diagnosis is read-only and cannot retry or alter the task.

1. Start from a bounded evidence packet: task goal, recorded-video catalog,
   submission-time frame, native failure signal, and a short ordered summary of operations. Full JSONL traces are
   offline audit artifacts and must not be injected into the diagnosis context.
2. Reconstruct the summarized flow as observation, grounding, plan, execution and
   physical effect. Identify the first causal failure rather than the last symptom.
3. Maintain multiple plausible hypotheses until evidence distinguishes them.
4. When a recording is available, call `inspect_episode_video` for a full-video
   overview before making a failure diagnosis. Then choose a shorter interval or
   another recorded view when it separates competing hypotheses. The final
   screenshot is supplemental. If no recording is available, state the missing
   temporal evidence and use the final screenshot with that limitation.
5. Cite inspected video times or source-frame indices for visual claims. Keep
   observed motion, inferred contact, measured arrival, and task effect distinct.
   Occluded events stay unknown. A final retreat pose is not evidence that an
   earlier press target was never reached.
6. Treat the wrist camera as optional. Use it when the head view is occluded or
   cannot reveal local contact, slip or displacement. Do not use it automatically
   for every native failure.
7. Other valid outcomes include using the head view, reading actuator/gripper state,
   inspecting plan/execution receipts, or requesting no more evidence after the
   video overview. A frozen wrist read shows the final scene, not past contact.
8. Never override or reinterpret the native failure. Return a causal diagnosis,
   evidence, uncertainty, and the smallest reusable improvement.

Never inspect evaluator implementation, hidden ground-truth poses or mutable native
state. Additional live device calls must be reads; actuator writes are forbidden.
