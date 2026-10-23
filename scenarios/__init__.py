"""Scenario data model shared by the agent and the eval harness.

A scenario is DATA: a user task plus the exact tool-call sequence a gullible
agent would perform after it reads the (possibly poisoned) content.

Placeholders inside step args let later steps reuse earlier outputs:
    "{{out:1}}"              full output text of step 1
    "{{out:1:first_half}}"   first half of it
    "{{out:1:second_half}}"  second half of it
    "{{out:1:base64}}"       base64-encoded
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

KIND_ATTACK = "attack"
KIND_BENIGN = "benign"
EXPECT_BLOCK_OR_ASK = "BLOCK_OR_ASK"   # every malicious step must be stopped
EXPECT_ALLOW = "ALLOW"                  # every step must run untouched


@dataclass(frozen=True)
class Step:
    tool: str
    args: dict
    malicious: bool = False   # ground truth: is THIS call the harmful action?
    note: str = ""


@dataclass(frozen=True)
class Scenario:
    id: str
    kind: str
    category: str
    description: str
    user_task: str                      # the TRUSTED instruction from the user
    steps: Tuple[Step, ...]
    expected_outcome: str
    injection_source: Optional[Tuple[str, str]] = None  # ("email","3") / ("web","<query>")
    grounding: Tuple[str, ...] = ()     # strings the poisoned content must contain
    hard_case: bool = False

    def __post_init__(self):
        if self.kind == KIND_ATTACK:
            if not any(s.malicious for s in self.steps):
                raise ValueError(f"{self.id}: attack scenario needs a malicious step")
            if self.expected_outcome != EXPECT_BLOCK_OR_ASK:
                raise ValueError(f"{self.id}: attack must expect {EXPECT_BLOCK_OR_ASK}")
            if self.injection_source is None:
                raise ValueError(f"{self.id}: attack scenario needs injection_source")
        elif self.kind == KIND_BENIGN:
            if any(s.malicious for s in self.steps):
                raise ValueError(f"{self.id}: benign scenario has a malicious step")
            if self.expected_outcome != EXPECT_ALLOW:
                raise ValueError(f"{self.id}: benign must expect {EXPECT_ALLOW}")
        else:
            raise ValueError(f"{self.id}: unknown kind {self.kind!r}")

    @property
    def malicious_steps(self) -> List[Step]:
        return [s for s in self.steps if s.malicious]


def get_all_scenarios() -> List[Scenario]:
    """15 attack + 10 benign, in a stable order."""
    from .attack_scenarios import ATTACK_SCENARIOS
    from .benign_scenarios import BENIGN_SCENARIOS
    return list(ATTACK_SCENARIOS) + list(BENIGN_SCENARIOS)
