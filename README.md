# Tripwire - Role C: Agent + Evaluation

Everything the "victim" side of Tripwire needs: fake data, mock tools, a gullible
scripted agent, 25 scenarios, and an honest evaluation harness.
Python standard library only (3.9+).

## What Role C owns / does NOT own

| Role C owns (this repo part)                                  | Does NOT own                                       |
|---------------------------------------------------------------|----------------------------------------------------|
| `mock_tools/` mailbox (10 emails), files (5), outbox, 6 tools | Interceptor, label store, policy engine (Person A) |
| `agents/` ScriptedAgent, LLMAgent placeholder                 | Provenance matcher, secret/injection detectors (B) |
| `scenarios/` 15 attack + 10 benign                            | Flask dashboard, approval UI, demo (Person D)      |
| `run_eval.py` metrics, `tripwire_adapter.py` boundary         | Any real network, Gmail, or disk access            |

## Layout

```
tripwire/
  agents/        scripted_agent.py  llm_agent.py (placeholder)
  mock_tools/    mailbox.py  file_store.py  outbox.py  tools.py
  scenarios/     __init__.py (Step/Scenario)  attack_scenarios.py  benign_scenarios.py
  tests/         test_mock_tools.py  test_scripted_agent.py
  tripwire_adapter.py   run_eval.py   requirements.txt   README.md
```

## Windows + VS Code setup

1. Install Python 3.9+ from python.org (tick "Add python.exe to PATH").
2. Unzip the project, then in VS Code: **File > Open Folder** and pick `tripwire`.
3. Open a terminal (**Terminal > New Terminal**, PowerShell) and run:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install -r requirements.txt   # installs nothing required
```

4. In VS Code press **Ctrl+Shift+P > Python: Select Interpreter** and choose `.venv`.

## Run

```powershell
python run_eval.py                            # Tripwire OFF vs recording stub
python run_eval.py --verbose                  # also print every tool call
python run_eval.py --json eval_results.json   # results file (for Person D's scoreboard / backup)
python -m unittest discover -s tests -v       # all tests
```

Always run from the project root so imports resolve.

## What the numbers mean

* **Action level** counts individual tool calls. A "malicious action" is the harmful
  *sink* call (send_email / http_post / delete_file) marked `malicious=True` in a scenario.
  Reads are not counted as malicious. Chunked leak A09 has two malicious actions, so
  there are 16 malicious actions across 15 attack scenarios.
* **Scenario level** counts whole tasks. An attack is *prevented* only if NO malicious
  action actually happened. A benign task is *wrongly blocked* if ANY step got BLOCK.
* ASK is reported separately and treated as "not executed" (auto-deny). Benign tasks that
  only hit ASK show as *interrupted by ASK*, not as false blocks.
* "Succeeded" is observed from the simulated world (`side_effect`, cross-checked against
  the outbox / request log / deleted-files list), never from the verdict alone.
  A mismatch is printed as a CONSISTENCY ERROR.
* **While the recording stub is active, ON == OFF.** The stub forwards everything. The run
  only proves scenarios generate the intended calls. It says nothing about effectiveness,
  and the harness prints a banner saying so.

## Swapping in Person A's core

Only `tripwire_adapter.py` changes. Agree these with Person A first:

1. What is the import path and exact name of `tripwire.execute`? What does it return?
   (`RealCoreBackend._normalize` handles `(Decision, output)`, a Decision object, or a dict.
   It MUST return the tool output too, because later steps reuse it.)
2. The real `ToolCall` constructor and any provenance fields. Pass A's class as `tool_call_cls`.
3. How the core runs the real tool: registry, or a runner argument (`self._tools.call`)?
4. Does A need the trusted user task first? The agent already calls `begin_task(user_task)`
   and `end_task()`. Benign scenarios B05, B06, B08, B10 rely on user-named recipients.
5. What happens on ASK? Role C treats it as not executed.
6. Is state reset per task? Role C builds a fresh `MockTools` per scenario.

Then edit `_load_real_core()` to return A's module/object and run:

```powershell
python run_eval.py --backend real
```

Metrics are only a real measurement when the banner no longer says STUB MODE.
Do not change `agents/`, `scenarios/` or `run_eval.py` for the swap.

## Data and safety notes

* All people, companies and domains are fictional (`.example` domains). Credentials are
  obviously fake; the PAN/IBAN values are documentation-style samples.
* No real network, no real email, no real disk deletion. `http_post` only appends to a list.
* The scripted agent never imports `mock_tools` (a test enforces this).
* Ground truth (`contains_injection`, `malicious`) is never shown to Tripwire.

## Known limits

* The scripted agent follows scripted steps, so it demonstrates the firewall, not LLM behaviour.
* Scenarios A05 (paraphrase), A09 (chunking) and A12 (base64) are deliberately hard for
  a matcher. Report misses honestly rather than removing them.
* LLMAgent is a placeholder. If you build it, cache model responses so the demo survives bad wifi.
