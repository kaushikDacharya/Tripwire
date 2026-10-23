from dataclasses import dataclass, field

UNTRUSTED, SECRET = "***", "SECRET"

@dataclass
class Span:
    text: str
    labels: set
    source: str

@dataclass
class Facts:
    recipient_untrusted: bool = False
    body_secret: bool = False
    recipient_in_allowlist: bool = False
    untrusted_in_context: bool = False
    injection_high: bool = False
    evidence: list = field(default_factory=list)

@dataclass
class Decision:
    action: str      # "allow" | "block" | "ask"
    rule_id: str
    reason: str
    evidence: list = field(default_factory=list)
