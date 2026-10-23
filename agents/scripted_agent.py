"""ScriptedAgent: a deterministic, deliberately gullible agent (no LLM).

It follows the step list of a Scenario. For every step it:
  1. fills in {{out:N}} placeholders from earlier tool outputs,
  2. sends the call through the Tripwire backend (the ONLY way to act),
  3. records the verdict, reason code and what really happened.

It never imports or calls mock_tools: it cannot bypass Tripwire even by accident.
(A unit test enforces this.)
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import Any, List

from scenarios import Scenario
from tripwire_adapter import BLOCK, ExecResult

_PLACEHOLDER = re.compile(r"\{\{out:(\d+)(?::([a-z_0-9]+))?\}\}")

MODIFIERS = {
    "first_half": lambda t: t[: len(t) // 2],
    "second_half": lambda t: t[len(t) // 2:],
    "base64": lambda t: base64.b64encode(t.encode("utf-8")).decode("ascii"),
}


def resolve_placeholders(value: Any, outputs: List[str]) -> Any:
    """Replace {{out:N[:modifier]}} in strings (recursively in dicts/lists).

    A missing or blocked step yields "" so the run continues deterministically.
    """
    if isinstance(value, str):
        def repl(m):
            idx, mod = int(m.group(1)), m.group(2)
            text = outputs[idx] if idx < len(outputs) else ""
            if mod is not None:
                if mod not in MODIFIERS:
                    raise ValueError(f"Unknown placeholder modifier: {mod!r}")
                text = MODIFIERS[mod](text)
            return text
        return _PLACEHOLDER.sub(repl, value)
    if isinstance(value, dict):
        return {k: resolve_placeholders(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_placeholders(v, outputs) for v in value]
    return value


@dataclass
class StepRecord:
    index: int
    tool: str
    args: dict                 # after placeholder resolution (what was really sent)
    malicious: bool            # ground truth from the scenario
    verdict: str
    reason_code: str
    evidence: List[str]
    executed: bool             # did the tool run?
    side_effect: bool          # did a simulated send/POST/delete really happen?
    output_preview: str


@dataclass
class RunTrace:
    scenario_id: str
    user_task: str
    backend_name: str
    is_real_core: bool
    steps: List[StepRecord] = field(default_factory=list)

    def verdicts(self) -> List[str]:
        return [s.verdict for s in self.steps]


def _output_text(result: ExecResult) -> str:
    """Text a gullible agent 'sees' from a tool result ('' if the tool did not run)."""
    if not result.executed or not result.output:
        return ""
    out = result.output
    return str(out.get("content") or out.get("message") or out.get("error") or "")


class ScriptedAgent:
    name = "ScriptedAgent"

    def __init__(self, backend, stop_on_block: bool = False):
        self.backend = backend
        self.stop_on_block = stop_on_block   # default: keep trying, like a gullible agent

    def run(self, scenario: Scenario) -> RunTrace:
        trace = RunTrace(scenario.id, scenario.user_task,
                         getattr(self.backend, "name", "unknown"),
                         bool(getattr(self.backend, "is_real_core", False)))
        outputs: List[str] = []
        self.backend.begin_task(scenario.user_task)
        try:
            for i, step in enumerate(scenario.steps):
                args = resolve_placeholders(step.args, outputs)
                result = self.backend.execute(step.tool, args)
                text = _output_text(result)
                outputs.append(text)
                trace.steps.append(StepRecord(
                    index=i, tool=step.tool, args=args, malicious=step.malicious,
                    verdict=result.verdict, reason_code=result.reason_code,
                    evidence=[str(e) for e in result.evidence],
                    executed=result.executed, side_effect=result.side_effect,
                    output_preview=text[:80].replace("\n", " "),
                ))
                if self.stop_on_block and result.verdict == BLOCK:
                    break
        finally:
            self.backend.end_task()
        return trace
