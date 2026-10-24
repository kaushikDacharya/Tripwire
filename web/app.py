from flask import Flask, jsonify, render_template, request
import mock_data

app = Flask(__name__)

# ---- pending approvals (ASK decisions waiting for a human) ----
PENDING = {}      # id -> entry
DECISIONS = {}    # id -> "approve" | "deny"

@app.route("/")
def dashboard():
    return render_template("dashboard.html")

@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/api/audit")
def audit():
    # Polled by JS every second. Later: return real log from core/tripwire
    since = int(request.args.get("since", 0))
    return jsonify([e for e in mock_data.AUDIT_LOG if e["id"] > since])

@app.route("/api/pending")
def pending():
    return jsonify([e for e in mock_data.AUDIT_LOG
                    if e["verdict"] == "ASK" and e["id"] not in DECISIONS])

@app.route("/api/approve/<int:eid>", methods=["POST"])
def approve(eid):
    DECISIONS[eid] = request.json.get("action", "deny")   # "approve" / "deny"
    return jsonify({"id": eid, "decision": DECISIONS[eid]})

@app.route("/api/scoreboard")
def scoreboard():
    return jsonify(mock_data.SCOREBOARD)

@app.route("/api/run", methods=["POST"])
def run_scenario():
    # body: {"scenario": "payroll_exfil", "tripwire": true/false}
    # Later: call agents + tripwire here. Now: return mock outbox.
    on = request.json.get("tripwire", True)
    return jsonify({"outbox": mock_data.OUTBOX_ON if on else mock_data.OUTBOX_OFF,
                    "tripwire": on})

if __name__ == "__main__":
    app.run(debug=True, port=5000)