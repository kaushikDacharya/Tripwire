from flask import Flask, jsonify, render_template, request

import mock_data as md  # swap for the real Tripwire modules once merged

app = Flask(__name__)


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


# ---- firewall mode -------------------------------------------------------
@app.route("/api/firewall", methods=["GET", "POST"])
def firewall():
    if request.method == "POST":
        md.set_firewall(bool((request.get_json(silent=True) or {}).get("on", True)))
    return jsonify({"on": md.STATE["firewall"]})


# ---- live audit log, approvals, history ----------------------------------
@app.route("/api/audit")
def audit():
    return jsonify(md.AUDIT_LOG[-150:])


@app.route("/api/pending")
def pending():
    return jsonify([e for e in md.AUDIT_LOG if e["status"] == "pending"])


@app.route("/api/decide/<int:entry_id>", methods=["POST"])
def decide(entry_id):
    action = (request.get_json(silent=True) or {}).get("action", "deny")
    result = md.decide(entry_id, action)
    if result is None:
        return jsonify({"error": "nothing pending with that id"}), 404
    return jsonify(result)


@app.route("/api/history")
def history():
    return jsonify(md.history())


@app.route("/api/reset", methods=["POST"])
def reset():
    md.reset()
    return jsonify({"ok": True})


# ---- scenarios and scoreboard --------------------------------------------
@app.route("/api/scenarios")
def scenarios():
    return jsonify([{"key": k, "label": v["label"], "type": v["type"]}
                    for k, v in md.SCENARIOS.items()])


@app.route("/api/run", methods=["POST"])
def run_scenario():
    body = request.get_json(silent=True) or {}
    key = body.get("scenario")
    if key not in md.SCENARIOS:
        return jsonify({"error": "unknown scenario"}), 400
    # "tripwire": true/false forces a mode (used by Compare); omitted = current mode
    on = body.get("tripwire")
    on = md.STATE["firewall"] if on is None else bool(on)
    return jsonify(md.simulate(key, on))


@app.route("/api/scoreboard")
def scoreboard():
    return jsonify(md.SCOREBOARD)


if __name__ == "__main__":
    app.run(debug=True, port=5000)