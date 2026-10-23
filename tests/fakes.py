from models import Facts

class FakeMatcher:
    def __init__(self, preset_facts: Facts = None):
        self.preset_facts = preset_facts

    def derive_facts(self, name, args, labels, allowlist):
        if self.preset_facts is None:
            return Facts()
        import copy
        return copy.deepcopy(self.preset_facts)

class FakeDetector:
    def __init__(self, score_val: float = 0.0):
        self.score_val = score_val

    def score(self, text: str) -> float:
        return self.score_val

def fake_tools():
    outbox = []
    
    def send_email(to, subject, body):
        outbox.append(to)
        return f"Email sent to {to}"
    
    def http_post(url, data):
        outbox.append(url)
        return f"Posted to {url}"

    def read_email(id):
        return "This is an email body"
    
    def read_file(name):
        return f"Contents of {name}"

    def search_web(q):
        return "Web result text"

    def delete_file(name):
        return f"Deleted {name}"

    tools = {
        "send_email": send_email,
        "http_post": http_post,
        "read_email": read_email,
        "read_file": read_file,
        "search_web": search_web,
        "delete_file": delete_file,
    }
    return tools, outbox
