import pytest
import yaml
from models import Facts
from policy import Policy

def test_rules_firing():
    p = Policy("policy.yaml")
    
    # R0: untrusted recipient AND secret body
    f0 = Facts(recipient_untrusted=True, body_secret=True, recipient_in_allowlist=False)
    assert p.evaluate(f0).rule_id == "R0"
    
    # R1: secret body (not allowlisted)
    f1 = Facts(body_secret=True, recipient_in_allowlist=False)
    assert p.evaluate(f1).rule_id == "R1"
    
    # R2: untrusted recipient
    f2 = Facts(recipient_untrusted=True, recipient_in_allowlist=False)
    assert p.evaluate(f2).rule_id == "R2"
    
    # R3: untrusted context AND injection high
    f3 = Facts(untrusted_in_context=True, injection_high=True, recipient_in_allowlist=False)
    assert p.evaluate(f3).rule_id == "R3"
    
    # R4: untrusted context
    f4 = Facts(untrusted_in_context=True, recipient_in_allowlist=False)
    assert p.evaluate(f4).rule_id == "R4"

def test_allowlist_bypass():
    p = Policy("policy.yaml")
    f = Facts(body_secret=True, recipient_in_allowlist=True)
    assert p.evaluate(f).rule_id == "DEFAULT"
    assert p.evaluate(f).action == "allow"

def test_rule_order():
    p = Policy("policy.yaml")
    f = Facts(recipient_untrusted=True, body_secret=True, recipient_in_allowlist=False)
    assert p.evaluate(f).rule_id == "R0"

def test_validation_errors(tmp_path):
    def write_yaml(content):
        f = tmp_path / "bad_policy.yaml"
        f.write_text(yaml.dump(content))
        return str(f)

    bad1 = write_yaml({"default": "allow", "rules": [{"id": "R1", "action": "allow"}]})
    with pytest.raises(ValueError, match="missing required field"):
        Policy(bad1)
    
    bad2 = write_yaml({"default": "allow", "rules": [{"id": "R1", "when": {}, "action": "boom", "reason": "x"}]})
    with pytest.raises(ValueError, match="invalid action"):
        Policy(bad2)

    bad3 = write_yaml({"default": "allow", "rules": [{"id": "R1", "when": {"fake": True}, "action": "allow", "reason": "x"}]})
    with pytest.raises(ValueError, match="invalid 'when' key"):
        Policy(bad3)

    bad4 = write_yaml({"default": "allow", "rules": [
        {"id": "R1", "when": {}, "action": "allow", "reason": "x"},
        {"id": "R1", "when": {}, "action": "allow", "reason": "y"}
    ]})
    with pytest.raises(ValueError, match="Duplicate rule id"):
        Policy(bad4)
