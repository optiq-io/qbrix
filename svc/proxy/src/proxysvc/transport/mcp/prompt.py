from __future__ import annotations

from typing import Annotated
from typing import Optional

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.prompts.base import Prompt
from pydantic import Field

_NO_CHANGE = "Make no change until I agree."


def _steps(opening: str, steps: list[str]) -> str:
    numbered = "\n".join(f"{n}. {step}" for n, step in enumerate(steps, start=1))
    return f"{opening}\n\n{numbered}"


def start_loop(
    choice: Annotated[
        Optional[str],
        Field(description="The product choice to decide, in a few words."),
    ] = None,
) -> str:
    """From a product choice to a draft loop wired into the code, ready to launch."""
    opening = (
        f"Help me set up a qbrix loop for: {choice}."
        if choice
        else "Help me set up a qbrix loop."
    )
    return _steps(
        opening,
        [
            "Ask me what is being decided and which result counts as success, "
            "unless that is clear already.",
            "Propose the options, each with the config the code will read, and "
            "wait for my go-ahead.",
            "Call `metrics_list` and pick the metric that stands for that result, "
            "or propose one with `metric_create`.",
            "Create the loop as a draft with `loop_create`, with a reason.",
            "Use `docs_search` and `loop_get` for how to call `select` and "
            "`outcome` or `track` in this codebase, and open a pull request that "
            "wires them, with qbrix:<key> in its title or description.",
            "Propose launching it with `loop_launch`. It usually waits for my "
            "approval: tell me where to approve it, and check on it with "
            "`change_get`.",
        ],
    )


def explain_loop(
    loop: Annotated[str, Field(description="The loop's key or its id.")],
) -> str:
    """What a loop is doing and what changed, in plain words, with one next step."""
    return _steps(
        f"Explain the qbrix loop {loop} to me in plain words.",
        [
            "Read it with `loop_get`, `loop_results` and `loop_history`.",
            "Say what is happening: each option's share of decisions, lift over "
            "an even split, the loop's health and any open alert, and how many "
            "decisions are waiting to seal.",
            "Say what changed and by whom. Where a shift follows a change, put "
            'the two side by side with both times and say "likely" at most.',
            "Read its declined changes and their reasons.",
            "If qbrix paused the loop for safety, find the cause with me first. "
            "Propose `loop_resume` only once the cause is understood, never as "
            "the alternative to finding it.",
            "Propose one next step with its reason, one that doesn't repeat a "
            "declined change whose reason still holds, or say that none is "
            f"needed. {_NO_CHANGE}",
        ],
    )


def weekly_review(
    since: Annotated[
        Optional[str],
        Field(description="Where the review starts; 7 days ago when left out."),
    ] = None,
) -> str:
    """Across the workspace's loops: what moved, what needs a look, what changed."""
    span = f"since {since}" if since else "over the last 7 days"
    read = (
        f"Read it with `workspace_summary`, from {since}."
        if since
        else "Read it with `workspace_summary`."
    )
    return _steps(
        f"Review my qbrix workspace {span}.",
        [
            read,
            "Start with the loops that need a look: open alerts and safety pauses.",
            "Say what moved, with the change beside it and both times, "
            '"likely" at most.',
            "Name the loops where one option has held most of the decisions, in "
            "share and lift. If committing one seems right, propose "
            "`loop_commit` with your reason; whether to commit is mine to decide.",
            "Say what changed and by whom.",
            "Propose at most one change per loop, each with its reason, after "
            "reading the loop's declined changes in `loop_get`; leave out any a "
            f"declined change's reason still rules out. {_NO_CHANGE}",
        ],
    )


PROMPTS = {
    "start-loop": start_loop,
    "explain-loop": explain_loop,
    "weekly-review": weekly_review,
}


def register(server: MCPServer) -> None:
    """add the prompts to the server, in the order prompts/list returns them."""
    for name, fn in PROMPTS.items():
        server.add_prompt(Prompt.from_function(fn, name=name))
