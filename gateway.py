import time
import uuid
from typing import Any, Callable
from models import Decision, UNTRUSTED, SECRET
from label_store import LabelStore

SOURCES = {"read_email": True, "search_web": True, "read_file": False}
SINKS = {"send_email", "http_post", "delete_file"}
INJECTION_THRESHOLD = 0.7

class Gateway:
    """Deterministic security gateway for AI agent tool calls."""

    def __init__(
        self, 
        tools: dict[str, Callable], 
        matcher: Any, 
        policy: Any, 
        detector: Any, 
        sensitive_files: tuple[str, ...] = (), 
        enabled: bool = True
    ) -> None:
        self.tools = tools
        self.matcher = matcher
        self.policy = policy
        self.detector = detector
        self.sensitive_files = sensitive_files
        self.enabled = enabled
        
        self.labels = LabelStore()
        self.log: list[dict] = []
        self.pending: dict[str, tuple[str, dict]] = {}

    def call(self, tool_name: str, **args: Any) -> Any:
        """Main entry point for tool execution."""
        if tool_name not in self.tools:
            return f"[UNKNOWN TOOL: {tool_name}]"

        if tool_name in SINKS:
            return self._sink(tool_name, args)

        try:
            result = self.tools[tool_name](**args)
            if tool_name in SOURCES:
                is_secret = False
                if tool_name == "read_file" and args.get("name") in self.sensitive_files:
                    is_secret = True
                
                self.labels.add(
                    text=result, 
                    source=f"{tool_name}:{args}", 
                    untrusted=SOURCES[tool_name], 
                    secret=is_secret
                )
            return result
        except Exception as e:
            return f"[TOOL ERROR: {e}]"

    def _sink(self, name: str, args: dict) -> Any:
        """Handles policy enforcement for sink tools."""
        if not self.enabled:
            decision = Decision("allow", "OFF", "Tripwire disabled")
            self._record(name, args, decision)
            try:
                return self.tools[name](**args)
            except Exception as e:
                return f"[TOOL ERROR: {e}]"

        try:
            facts = self.matcher.derive_facts(name, args, self.labels, self.policy.allowlist)
            
            untrusted_spans = self.labels.with_label(UNTRUSTED)
            if any(self.detector.score(s.text) >= INJECTION_THRESHOLD for s in untrusted_spans):
                facts.injection_high = True
            
            decision = self.policy.evaluate(facts)
        except Exception as e:
            decision = Decision("block", "ERROR", f"Tripwire internal error: {e}")

        if decision.action == "allow":
            self._record(name, args, decision)
            try:
                return self.tools[name](**args)
            except Exception as e:
                return f"[TOOL ERROR: {e}]"
        
        elif decision.action == "ask":
            pid = uuid.uuid4().hex[:8]
            self.pending[pid] = (name, args)
            self._record(name, args, decision, pending_id=pid)
            return f"[PENDING_APPROVAL {pid}]"
        
        else: # block
            self._record(name, args, decision)
            return f"[BLOCKED: {decision.reason}]"

    def resolve(self, pid: str, approve: bool) -> Any:
        """Resolves a pending tool call based on human approval."""
        if pid not in self.pending:
            return "[UNKNOWN APPROVAL ID]"
        
        name, args = self.pending.pop(pid)
        if approve:
            try:
                result = self.tools[name](**args)
                self._record(name, args, Decision("allow", "HUMAN_APPROVED", "Approved by human"))
                return result
            except Exception as e:
                return f"[TOOL ERROR: {e}]"
        else:
            self._record(name, args, Decision("block", "HUMAN_DENIED", "Denied by human"))
            return "[DENIED]"

    def _record(self, tool: str, args: dict, decision: Decision, pending_id: str = None) -> dict:
        """Logs a security decision in a JSON-serializable format."""
        record = {
            "t": time.time(),
            "tool": tool,
            "args": args,
            "action": decision.action,
            "rule": decision.rule_id,
            "reason": decision.reason,
            "evidence": list(decision.evidence) if decision.evidence else []
        }
        if pending_id:
            record["pending_id"] = pending_id
        
        self.log.append(record)
        return record
