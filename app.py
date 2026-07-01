import os
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

import storage
import detection
import labels

load_dotenv()

app = Flask(__name__)

# Rate limiting is keyed by remote address for this project (no auth layer
# exists yet). In production this would be keyed by authenticated creator_id
# instead, so one creator can't be starved by traffic from other users on
# the same IP/NAT. See README "Rate limiting" for the reasoning behind the
# specific numbers (10/minute, 100/day).
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

storage.init_db()


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    creator_id = data.get("creator_id")

    if not text or not isinstance(text, str) or not text.strip():
        return jsonify({"error": "text field is required and must be non-empty"}), 400
    if not creator_id:
        return jsonify({"error": "creator_id field is required"}), 400

    llm_result = detection.llm_signal(text)
    style_result = detection.stylometric_signal(text)
    confidence = detection.combine_signals(llm_result, style_result)
    attribution = labels.classify(confidence)
    label = labels.label_for(attribution)

    content_id, created_at = storage.save_submission(
        creator_id=creator_id,
        text=text,
        llm_score=llm_result["score"],
        style_score=style_result["score"],
        confidence=confidence,
        attribution=attribution,
        label=label,
    )

    return jsonify({
        "content_id": content_id,
        "created_at": created_at,
        "attribution": attribution,
        "confidence": confidence,
        "label": label,
        "signals": {
            "llm": {
                "score": llm_result["score"],
                "reasoning": llm_result.get("reasoning"),
                "source": llm_result.get("source"),
            },
            "stylometric": {
                "score": style_result["score"],
                "metrics": style_result.get("metrics"),
            },
        },
        "status": "classified",
    }), 200


@app.route("/appeal", methods=["POST"])
def appeal():
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id")
    creator_reasoning = data.get("creator_reasoning")

    if not content_id or not creator_reasoning:
        return jsonify({"error": "content_id and creator_reasoning are both required"}), 400

    submission = storage.get_submission(content_id)
    if submission is None:
        return jsonify({"error": f"no submission found with content_id {content_id}"}), 404

    timestamp = storage.file_appeal(content_id, creator_reasoning)

    return jsonify({
        "content_id": content_id,
        "status": "under_review",
        "message": (
            "Your appeal has been received and logged. A human reviewer will "
            "look at the original classification alongside your reasoning."
        ),
        "filed_at": timestamp,
    }), 200


@app.route("/log", methods=["GET"])
def log():
    limit = request.args.get("limit", default=50, type=int)
    return jsonify({"entries": storage.get_log(limit)}), 200


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "Provenance Guard",
        "endpoints": ["POST /submit", "POST /appeal", "GET /log"],
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
