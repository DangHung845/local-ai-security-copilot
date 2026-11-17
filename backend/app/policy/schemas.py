from dataclasses import dataclass, field
from enum import Enum


class Decision(str, Enum):
    ALLOW = "allow"
    REDIRECT = "redirect"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    category: str
    reason: str
    matched_rules: tuple[str, ...] = field(default_factory=tuple)
    hitl_required: bool = False
