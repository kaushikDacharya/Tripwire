"""Tripwire Live Gmail Agent — Instruction Follower.

Monitors a real Gmail inbox via IMAP.  When a new email arrives the agent
reads it, extracts actionable instructions, and executes them through the
Tripwire backend adapter.

Supported instructions:
  • Forward an email          – "forward this to alice@example.com"
  • Reply / respond           – "reply saying thanks for the update"
  • Send a new email          – "send email to bob@example.com saying …"
  • Send a file as attachment – "send report.pdf to carol@example.com"
  • Make a payment            – "pay $50 to vendor@example.com for invoice 123"

Security / prompt‑injection scanning is NOT done here — that is Person B's
responsibility, enforced by the Tripwire adapter boundary.

Usage:
    python run_agent_gmail.py                 # start live listener (5 s poll)
    python run_agent_gmail.py --interval 10   # custom poll interval
    python run_agent_gmail.py --test          # run agent once on newest email
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Windows console UTF‑8 fix
# ---------------------------------------------------------------------------
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Make sure our package roots are importable
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
for _root in [
    _SCRIPT_DIR,
    os.path.join(_SCRIPT_DIR, "tripwire_role_c", "tripwire"),
    os.path.join(_SCRIPT_DIR, "files", "tripwire_role_c", "tripwire"),
    os.path.abspath(os.path.join(_SCRIPT_DIR, "..")),
]:
    if os.path.isdir(_root) and _root not in sys.path:
        sys.path.insert(0, _root)

try:
    from mock_tools.gmail_mailbox import GmailMailbox, load_gmail_credentials
    from mock_tools.tools import MockTools
    from tripwire_adapter import RecordingStubBackend
except ImportError:
    try:
        from gmail_mailbox import GmailMailbox, load_gmail_credentials
        from tools import MockTools
        from tripwire_adapter import RecordingStubBackend
    except ImportError as err:
        print(f"[!] Cannot import Tripwire modules: {err}")
        print("    Run this script from inside the tripwire project folder.")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
#  Instruction parser
# ═══════════════════════════════════════════════════════════════════════════

_EMAIL_RE = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"


def _extract_email_address(header: str) -> str:
    """Pull a clean address out of a From: header."""
    m = re.search(_EMAIL_RE, header)
    return m.group(0) if m else header.strip()


def _clean_quotes(s: str) -> str:
    """Strip surrounding quotes and trailing periods/whitespace."""
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    if (s.startswith('“') and s.endswith('”')) or (s.startswith('‘') and s.endswith('’')):
        s = s[1:-1].strip()
    return s.rstrip(".").strip()


def parse_instructions(body: str, meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return a list of tool‑call dicts extracted from the email body.

    Each dict has keys: tool, args, description.
    """
    sender = meta.get("sender", "")
    sender_addr = _extract_email_address(sender)
    subject = meta.get("subject", "Message")

    # Strip email headers that were prepended by the read tool
    cleaned_lines: list[str] = []
    past_headers = False
    for line in body.split("\n"):
        stripped = line.strip()
        if not past_headers and (
            stripped.startswith("From:") or stripped.startswith("Subject:")
            or stripped.startswith("Date:")
        ):
            continue
        past_headers = True
        cleaned_lines.append(stripped)
    clean_body = "\n".join(cleaned_lines).strip()
    norm = re.sub(r"\s+", " ", clean_body)

    instructions: List[Dict[str, Any]] = []

    # 1. Forwarding: "forward ... to <addr>"
    fwd_m = re.search(
        rf"(?i)\b(?:forward|fwd|pass\s+along)\b.*?\bto\s+[\"'\s]*({_EMAIL_RE})[\"'\s]*",
        norm,
    )
    if fwd_m:
        target = fwd_m.group(1).strip()
        fwd_sub = subject if subject.lower().startswith("fwd:") else f"Fwd: {subject}"
        instructions.append({
            "tool": "send_email",
            "args": {
                "to": target,
                "subject": fwd_sub,
                "body": (
                    f"---------- Forwarded message ----------\n"
                    f"From: {sender}\nSubject: {subject}\n\n{clean_body}"
                ),
            },
            "description": f"Forward email to {target}",
        })
        return instructions

    # 2. Payment: "pay $X to <recipient>"
    pay_pat = (
        r"(?i)\b(?:pay|transfer|make\s+(?:a\s+)?payment\s*(?:of)?|send\s+payment\s*(?:of)?)\s*"
        r"\$?([0-9]+(?:\.[0-9]+)?)\s*(?:dollars|usd)?\s*"
        r"(?:to\s+)?([\"']?[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}[\"']?|[a-zA-Z0-9_\-]+)\s*"
        r"(?:(?:for|memo:?)\s+([^.\n\r]+))?"
    )
    pay_m = re.search(pay_pat, norm)
    if pay_m:
        amount = float(pay_m.group(1))
        recipient = pay_m.group(2).strip().strip("'\"")
        memo = (pay_m.group(3) or "").strip() or f"Payment for: {subject}"
        instructions.append({
            "tool": "make_payment",
            "args": {"to": recipient, "amount": amount, "memo": memo},
            "description": f"Pay ${amount:.2f} to {recipient}",
        })
        return instructions

    # 3. File sending: "send <filename> to <addr>"
    file_m = re.search(
        rf"(?i)\b(?:send|email|forward|attach)\b.*?\b([a-zA-Z0-9_.\-]+\.[a-zA-Z0-9]{{2,4}})\b.*?\bto\s+[\"'\s]*({_EMAIL_RE})[\"'\s]*",
        norm,
    )
    if file_m:
        fname = file_m.group(1).strip()
        target = file_m.group(2).strip()
        instructions.append({
            "tool": "read_file",
            "args": {"filename": fname},
            "description": f"Read file {fname}",
        })
        instructions.append({
            "tool": "send_email",
            "args": {
                "to": target,
                "subject": f"Requested file: {fname}",
                "body": f"Attached: {fname}",
                "filename": fname,
            },
            "description": f"Email {fname} to {target}",
        })
        return instructions

    # 4. Blind obedience for Reply / Respond / Send Email / Mail:
    is_reply_intent = bool(
        re.search(
            r"(?i)\b(?:respond|reply|send|mail|email|write|tell|say|message|shoot|ping|answer|notify)\b",
            norm,
        )
    )

    if is_reply_intent:
        emails_in_body = re.findall(_EMAIL_RE, norm)
        # Use target from email body if specified, otherwise reply to the sender
        target = emails_in_body[0] if emails_in_body else sender_addr

        # Extract the message to send:
        # Check quoted strings first
        quoted_texts = re.findall(r'["“\']([^"”\']+)["”\']', norm)
        valid_quotes = [q.strip() for q in quoted_texts if "@" not in q and len(q.strip()) > 0]

        kw_m = re.search(r"(?i)\b(?:saying|with|stating|body|message)[:\s]+[\"'\s]*([^\"'\r\n]+)[\"'\s]*", norm)

        if valid_quotes:
            body_text = valid_quotes[-1]
        elif kw_m:
            body_text = _clean_quotes(kw_m.group(1))
        else:
            verb_m = re.search(r"(?i)\b(?:respond|reply|send|mail|email|write|say)[:\s]+(.*)", norm)
            if verb_m:
                body_text = _clean_quotes(verb_m.group(1))
            else:
                body_text = f"Acknowledging: {subject}"

        re_sub = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        instructions.append({
            "tool": "send_email",
            "args": {
                "to": target,
                "subject": re_sub,
                "body": body_text,
            },
            "description": f"Send response to {target}: \"{body_text}\"",
        })

    return instructions


# ═══════════════════════════════════════════════════════════════════════════
#  Agent activation — runs when a new email is detected
# ═══════════════════════════════════════════════════════════════════════════

def activate(mailbox: GmailMailbox, email_id: Any) -> None:
    """Read one email, extract instructions, execute them via Tripwire backend."""
    tools = MockTools(mailbox=mailbox, send_real_email=True)
    backend = RecordingStubBackend(tools)

    print("\n" + "=" * 72)
    print("  AGENT ACTIVATED — new email received")
    print("=" * 72)

    # Step 1 — read the email through the backend
    result = backend.execute("read_email", {"email_id": email_id})
    if not result.executed or not result.output or not result.output.get("ok"):
        err = (result.output or {}).get("error", "read_email failed")
        print(f"  [!] Could not read email {email_id}: {err}")
        return

    content = result.output.get("content", "")
    meta = result.output.get("meta", {})

    print(f"  From    : {meta.get('sender', '?')}")
    print(f"  Subject : {meta.get('subject', '?')}")
    print(f"  Date    : {meta.get('date', '?')}")
    print(f"  UID     : {meta.get('uid', email_id)}")
    print("-" * 72)

    # Step 2 — extract instructions
    instructions = parse_instructions(content, meta)

    if not instructions:
        print("  (No actionable instructions found — informational email.)\n")
        return

    print(f"  Found {len(instructions)} instruction(s):\n")

    # Step 3 — execute each instruction through the Tripwire adapter
    last_output = ""
    for idx, instr in enumerate(instructions, 1):
        tool = instr["tool"]
        args = dict(instr["args"])
        desc = instr["description"]

        # Allow chaining: if a body placeholder references prior output
        if args.get("body") == "{{output}}" and last_output:
            args["body"] = last_output

        print(f"  [{idx}] {desc}")
        print(f"      → {tool}({args})")

        res = backend.execute(tool, args)

        # Capture output for potential chaining
        if res.output and isinstance(res.output, dict):
            last_output = str(
                res.output.get("content")
                or res.output.get("message")
                or ""
            )

        # Report result
        verdict = getattr(res, "verdict", "ALLOW")
        if not res.executed or verdict == "BLOCK":
            reason = getattr(res, "reason_code", "blocked by policy")
            print(f"      ✗ BLOCKED by Tripwire boundary ({reason})")
        else:
            msg = (
                res.output.get("message")
                or res.output.get("content")
                or "done"
            )
            print(f"      ✓ {msg}")

    uid = meta.get("uid", email_id)
    print(f"\n  Finished processing email UID {uid}.\n")


# ═══════════════════════════════════════════════════════════════════════════
#  Live listener — polls Gmail for new UIDs with persistent connection
# ═══════════════════════════════════════════════════════════════════════════

def _highest_uid(mailbox: GmailMailbox) -> Optional[int]:
    """Return the highest numeric UID currently in INBOX, or None on error."""
    try:
        client = mailbox._connect()
        try:
            status, _ = client.select("INBOX", readonly=True)
            if status != "OK":
                return None
            status, data = client.uid("search", None, "ALL")
            if status == "OK" and data and data[0]:
                uids = [int(u) for u in data[0].split() if u.isdigit()]
                return max(uids) if uids else 0
            return 0
        finally:
            try:
                client.close()
            except Exception:
                pass
            try:
                client.logout()
            except Exception:
                pass
    except Exception as exc:
        print(f"[!] Gmail query error: {exc}")
        return None


def listen(mailbox: GmailMailbox, interval: int = 5) -> None:
    """Poll INBOX every *interval* seconds using a persistent connection with auto-reconnect."""
    print("=" * 72)
    print("  TRIPWIRE LIVE GMAIL AGENT")
    print(f"  Account  : {mailbox.email_address}")
    print(f"  Polling  : every {interval}s")
    print("  Actions  : forward · reply · send email · file attach · payment")
    print("  Security : Person B (Tripwire adapter) handles injection defence")
    print("  Status   : waiting for new emails …  (Ctrl+C to quit)")
    print("=" * 72)

    baseline = _highest_uid(mailbox)
    if baseline is None:
        print("[!] Cannot connect — check credentials in .env")
        return
    print(f"[ok] Connected. Baseline UID: {baseline}\n")

    client = None
    tick = 0

    def _get_client():
        nonlocal client
        if client is not None:
            try:
                status, _ = client.noop()
                if status == "OK":
                    return client
            except Exception:
                try:
                    client.close()
                except Exception:
                    pass
                try:
                    client.logout()
                except Exception:
                    pass
                client = None

        # Reconnect with retry
        for attempt in range(1, 4):
            try:
                client = mailbox._connect()
                client.select("INBOX", readonly=True)
                return client
            except Exception:
                client = None
                time.sleep(1.5 * attempt)
        return None

    try:
        while True:
            time.sleep(interval)
            tick += 1

            c = _get_client()
            if not c:
                continue

            try:
                status, _ = c.select("INBOX", readonly=True)
                if status != "OK":
                    client = None
                    continue

                status, data = c.uid("search", None, "ALL")
                if status != "OK" or not data or not data[0]:
                    continue

                all_uids = sorted(int(u) for u in data[0].split() if u.isdigit())
                new_uids = [u for u in all_uids if u > baseline]

                if new_uids:
                    print(f"\n[*] {len(new_uids)} new email(s) detected!")
                    for uid in new_uids:
                        baseline = max(baseline, uid)
                        mailbox._inbox_initialized = False  # force fresh fetch
                        activate(mailbox, str(uid))
                    print(f"[*] Listener resumed (highest UID: {baseline})")
                else:
                    # heartbeat every ~30 s
                    heartbeat_ticks = max(1, 30 // interval)
                    if tick % heartbeat_ticks == 0:
                        now = time.strftime("%H:%M:%S")
                        print(f"[{now}] listening … ({len(all_uids)} msgs in INBOX)")

            except Exception as loop_err:
                msg = str(loop_err)
                # Transient disconnects from Gmail are normal; reconnect silently next tick
                if "socket error" not in msg.lower() and "eof" not in msg.lower() and "abort" not in msg.lower():
                    print(f"[!] Warning during check: {loop_err}")
                try:
                    c.close()
                except Exception:
                    pass
                try:
                    c.logout()
                except Exception:
                    pass
                client = None

    except KeyboardInterrupt:
        print("\n\n[!] Listener stopped. Goodbye!")
    finally:
        if client:
            try:
                client.close()
            except Exception:
                pass
            try:
                client.logout()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(description="Tripwire Gmail Agent — live instruction follower")
    ap.add_argument("--interval", "-i", type=int, default=5, help="poll interval in seconds (default 5)")
    ap.add_argument("--test", "-t", action="store_true", help="run agent once on the newest email")
    args = ap.parse_args()

    addr, pwd = load_gmail_credentials()
    if not addr or not pwd:
        print("[!] Missing GMAIL_ADDRESS / GMAIL_APP_PASSWORD in .env — cannot start.")
        return

    mailbox = GmailMailbox()

    if args.test:
        print("[*] Test mode — running agent on newest email …")
        activate(mailbox, 1)
    else:
        listen(mailbox, interval=args.interval)


if __name__ == "__main__":
    main()
