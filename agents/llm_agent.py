"""LLMAgent: PLACEHOLDER ONLY. Build it only if the core pipeline is done.

Plan (about 60 lines, no frameworks):
  * Same interface as ScriptedAgent:  LLMAgent(backend).run(scenario) -> RunTrace
  * A plain `while` loop: send messages + tool schemas to Groq/Gemini/Ollama,
    and for every tool call the model asks for, call self.backend.execute(name, args).
    Never call mock tools directly.
  * Cache every model response in a JSON file keyed by a hash of (scenario id,
    message history), so the demo still works when wifi or the API fails.
  * Build RunTrace/StepRecord objects exactly like ScriptedAgent does.
"""


class LLMAgent:
    name = "LLMAgent (placeholder)"

    def __init__(self, backend, cache_path: str = "llm_cache.json"):
        self.backend = backend
        self.cache_path = cache_path

    def run(self, scenario):
        raise NotImplementedError("LLMAgent is optional and not implemented yet.")
