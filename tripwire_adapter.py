"""The ONLY file where Role C touches Person A's code.

The agent talks to a "backend" with this shape:

    backend.begin_task(user_task)        # optional hook, may be a no-op
    backend.execute(name, args) -> ExecResult
    backend.end_task()                   # optional hook, may be a no-op

Three backends are provided:

  PassthroughBackend    = "Tripwire OFF". Runs every tool call. No checks.
  RecordingStubBackend  = development stand-in for Tripwire ON. It records
                          every call and then RUNS it anyway. It enforces
                          NOTHING and must never be presented as a firewall.
  RealCoreBackend       = skeleton for Person A's core. Every line marked
                          CONFIRM must be checked with Person A.

To switch to the real core, only `_load_real_core()` and the CONFIRM lines
below should change. The agent, scenarios and run_eval.py stay untouched.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

ALLOW = "ALLOW"
ASK = "ASK"
BLOCK = "BLOCK"


@dataclass
class ToolCall:
    """TEMPORARY local mirror of the roadmap contract (name, args).

    CONFIRM with Person A: the real constructor (extra fields? provenance?).
    When A's class exists, pass it to RealCoreBackend(tool_call_cls=...).
    """
    name: str
    args: dict


@dataclass
class ExecResult:
    """What Role C needs back from one tool call, regardless of who produced it."""
    verdict: str                              # "ALLOW" | "ASK" | "BLOCK"
    reason_code: str = ""
    evidence: List[Any] = field(default_factory=list)
    output: Optional[dict] = None             # tool output dict if the tool ran
    executed: bool = False                    # True only if the tool really ran
    raw: Any = None                           # untouched return value, for debugging

    @property
    def side_effect(self) -> bool:
        """True only if a simulated email/POST/delete really happened."""
        return bool(self.executed and self.output and self.output.get("side_effect"))


class PassthroughBackend:
    """Tripwire OFF: run everything."""
    name = "Tripwire OFF (passthrough)"
    is_real_core = False

    def __init__(self, tools):
        self._tools = tools

    def begin_task(self, user_task: str) -> None:
        pass

    def end_task(self) -> None:
        pass

    def execute(self, name: str, args: dict) -> ExecResult:
        output = self._tools.call(name, dict(args))
        return ExecResult(ALLOW, "TRIPWIRE_OFF", [], output, True)


class RecordingStubBackend:
    """Development stub. Records calls, enforces NOTHING.

    It forwards every call to the tools, so attacks succeed exactly as with
    Tripwire OFF. Its only job is to prove the agent and scenarios generate the
    intended tool calls and that every call goes through this interface.
    """
    name = "RECORDING STUB (no enforcement)"
    is_real_core = False

    def __init__(self, tools):
        self._tools = tools
        self.calls: List[ToolCall] = []
        self.tasks: List[str] = []

    def begin_task(self, user_task: str) -> None:
        self.tasks.append(user_task)

    def end_task(self) -> None:
        pass

    def execute(self, name: str, args: dict) -> ExecResult:
        self.calls.append(ToolCall(name, dict(args)))
        output = self._tools.call(name, dict(args))
        return ExecResult(ALLOW, "RECORDING_STUB_NO_ENFORCEMENT", [], output, True)


class RealCoreBackend:
    """Skeleton for Person A's core. Fill in the CONFIRM lines, nothing else.

    Questions to settle with Person A (write the answers next to each line):
      1. Which module/function is `tripwire.execute`, and what does it return?
      2. How is a ToolCall built (fields, provenance)?
      3. How does the core learn to RUN a tool? (registry vs. runner argument)
      4. Does it need the user's task (trusted instruction) first? e.g. for
         "send to the address the user named" -> begin_task hook.
      5. What happens on ASK? Role C currently treats ASK as "not executed".
      6. Is state (label store) reset per task? Role C creates fresh tools per run.
    """
    name = "REAL TRIPWIRE CORE"
    is_real_core = True

    def __init__(self, core, tools, tool_call_cls=ToolCall):
        self._core = core
        self._tools = tools
        self._tool_call_cls = tool_call_cls

    def begin_task(self, user_task: str) -> None:
        hook = getattr(self._core, "begin_task", None)      # CONFIRM name/signature
        if callable(hook):
            hook(user_task)

    def end_task(self) -> None:
        hook = getattr(self._core, "end_task", None)        # CONFIRM name/signature
        if callable(hook):
            hook()

    def execute(self, name: str, args: dict) -> ExecResult:
        call = self._tool_call_cls(name, dict(args))        # CONFIRM constructor
        raw = self._core.execute(call)                      # CONFIRM call + tool wiring
        # If A's execute() needs a runner for the real tool, it may be:
        #     raw = self._core.execute(call, self._tools.call)
        return self._normalize(raw)

    @staticmethod
    def _normalize(raw) -> ExecResult:
        """CONFIRM the real return shape. Handles three likely shapes."""
        decision, output = raw, None
        if isinstance(raw, tuple) and len(raw) == 2:        # (Decision, tool_output)
            decision, output = raw
        if isinstance(decision, dict):
            verdict = decision.get("verdict")
            reason = decision.get("reason_code", "")
            evidence = decision.get("evidence", [])
            output = output if output is not None else decision.get("output")
        else:
            verdict = getattr(decision, "verdict", None)
            reason = getattr(decision, "reason_code", "")
            evidence = getattr(decision, "evidence", [])
        if verdict not in (ALLOW, ASK, BLOCK):
            raise ValueError(f"Unrecognised verdict from core: {verdict!r} (raw={raw!r})")
        # ASSUMPTION: only ALLOW means the tool ran. ASK is treated as "held".
        return ExecResult(verdict, reason or "", list(evidence or []), output,
                          executed=(verdict == ALLOW), raw=raw)


def _load_real_core():
    """Return Person A's tripwire core object (module or instance).

    Example once A's code is merged (names are PLACEHOLDERS, confirm them):
        import core.tripwire as tripwire
        return tripwire
    """
    raise NotImplementedError(
        "Person A's core is not wired in yet. Edit _load_real_core() in "
        "tripwire_adapter.py (see README: 'Swapping in Person A's core')."
    )


def make_backend(mode: str, tools):
    """mode: 'off' (passthrough) | 'stub' (recording stub) | 'real' (Person A's core)."""
    if mode == "off":
        return PassthroughBackend(tools)
    if mode == "stub":
        return RecordingStubBackend(tools)
    if mode == "real":
        return RealCoreBackend(_load_real_core(), tools)
    raise ValueError(f"Unknown backend mode: {mode!r}")
