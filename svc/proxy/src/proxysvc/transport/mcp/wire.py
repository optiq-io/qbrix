from __future__ import annotations

import json
from typing import Any

PYTHON_INSTALL = 'pip install "qbrix[http]==0.4.0a2"'
JAVASCRIPT_INSTALL = "npm install @optiqio/qbrix@next"


def _offline(loop: dict) -> dict[str, Any]:
    fallback = next(
        (option for option in loop["options"] if option["key"] == loop["fallback"]),
        None,
    )
    return {
        "key": loop["fallback"],
        "config": (fallback or {}).get("config") or {},
    }


def _outcome_note(metric_type: str) -> str:
    if metric_type == "conversion":
        return "1 when the user converted"
    return "the value the user's outcome measured"


def python(loop: dict, base_url: str) -> str:
    offline = repr(_offline(loop))
    return f"""# {PYTHON_INSTALL}
import os

from qbrix import Qbrix

client = Qbrix(api_key=os.environ["QBRIX_API_KEY"], base_url="{base_url}")

user_id = "user-1"
decision = client.select(
    "{loop["key"]}",
    context={{"unit": user_id}},
    settings={{"offline": {offline}}},
)
config = decision.option.config  # render this option

# later, {_outcome_note(loop["metric"]["type"])}
client.outcome(decision.request_id, 1)
"""


def javascript(loop: dict, base_url: str) -> str:
    offline = json.dumps(_offline(loop))
    return f"""// {JAVASCRIPT_INSTALL}
import {{ Qbrix }} from "@optiqio/qbrix";

const qbrix = new Qbrix({{ apiKey: process.env.QBRIX_API_KEY, baseUrl: "{base_url}" }});

const userId = "user-1";
const decision = await qbrix.select(
  "{loop["key"]}",
  {{ unit: userId }},
  {{ offline: {offline} }},
);
const config = decision.option?.config; // render this option

// later, {_outcome_note(loop["metric"]["type"])}
await qbrix.outcome(decision.requestId, 1);
"""


def wiring(loop: dict, base_url: str) -> dict[str, str]:
    """the select and outcome calls for this loop, in each SDK's next pre-release."""
    return {"python": python(loop, base_url), "javascript": javascript(loop, base_url)}
