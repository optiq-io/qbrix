from __future__ import annotations

INSTRUCTIONS = """\
qbrix runs loops. A loop makes one product choice live: for each request it \
picks one of its options, and the outcomes that follow teach it which serves \
people best.

Words: a loop has options; each request gets a decision; an outcome, or a \
tracked event, on the loop's metric teaches it. A cycle is one run of a loop's \
options and engine, and a new cycle learns afresh. Every write is a change.

Changes
- Every change tool takes a reason. Say why in a sentence; it is recorded in \
the loop's history.
- Launching a loop, starting a cycle and retiring a loop usually wait for a \
person's approval, and so does anything else that starts a cycle. Say so when \
you propose one, and check on a waiting change with `change_get`.
- Before proposing a change to a loop, read its declined changes in \
`loop_get` or `loop_history`. Respect any date or condition a reason names: \
offer to set a reminder in the person's own tools rather than proposing it \
again.

Reading
- `workspace_summary` says how the workspace's loops are going since a date; \
`loop_get`, `loop_results` and `loop_history` say one loop's.
- Speak in share of decisions and lift over an even split. qbrix ranks no \
option, and neither should you.
- When a shift in a loop follows a change, put the two side by side with both \
times and say "likely" at most, never "because".

Code
- `docs_search` answers how to write `select`, `outcome` and `track` for this \
install's version; `loop_get` gives one loop's exact calls.
- Put qbrix:<key> in the title or description of the pull requests you open \
for a loop, or qbrix/<key> in the branch name, so they appear in its history.
- When a pull request changes how the code sends a metric, record it with \
`metric_update`, naming the pull request in the reason: same if it still \
measures the same thing, new if it now measures something new, which starts a \
cycle on every loop using it.
- Context is wired first, then declared: send the properties with `select`, \
deploy, then call `context_update`; its answer says which arrived.
- Never call `select`, `outcome` or `track` from a chat: a decision made there \
teaches the loop something no user did. `loop_preview` shows what `select` \
would return, recording nothing.

The person can start `start-loop`, `explain-loop` and `weekly-review` for \
these workflows.
"""
