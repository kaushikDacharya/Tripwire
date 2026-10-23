import yaml
from models import Facts, Decision

class Policy:
    """Enforces security decisions based on tool call facts."""

    def __init__(self, path: str = "policy.yaml") -> None:
        self.path = path
        self.reload()

    def reload(self) -> None:
        """Loads and validates policy from YAML."""
        with open(self.path, "r") as f:
            data = yaml.safe_load(f)
        
        self.allowlist = [email.lower() for email in data.get("allowlist", [])]
        self.default = data.get("default")
        self.rules = data.get("rules", [])
        self._validate(data)

    def _validate(self, data: dict) -> None:
        """Validates policy structure and values."""
        if self.default not in {"allow", "block", "ask"}:
            raise ValueError(f"Invalid default action: {self.default}")

        rule_ids = set()
        valid_fact_fields = {f for f in Facts.__dataclass_fields__ if f != "evidence"}

        for i, rule in enumerate(self.rules):
            for field in {"id", "when", "action", "reason"}:
                if field not in rule:
                    raise ValueError(f"Rule {i} is missing required field: {field}")
            
            if rule["action"] not in {"allow", "block", "ask"}:
                raise ValueError(f"Rule {rule['id']} has invalid action: {rule['action']}")
            
            rid = rule["id"]
            if rid in rule_ids:
                raise ValueError(f"Duplicate rule id: {rid}")
            rule_ids.add(rid)

            for fact_key in rule["when"]:
                if fact_key not in valid_fact_fields:
                    raise ValueError(f"Rule {rid} contains invalid 'when' key: {fact_key}")

    def evaluate(self, facts: Facts) -> Decision:
        """Returns the decision of the first matching rule."""
        for rule in self.rules:
            match = True
            for key, value in rule["when"].items():
                if getattr(facts, key) != value:
                    match = False
                    break
            if match:
                return Decision(
                    action=rule["action"],
                    rule_id=rule["id"],
                    reason=rule["reason"],
                    evidence=facts.evidence
                )
        
        return Decision(
            action=self.default,
            rule_id="DEFAULT",
            reason="No rule matched",
            evidence=facts.evidence
        )
