#!/usr/bin/env python3
"""Flask webhook server for Jules Code Review GitHub App."""

import hashlib
import hmac
import json
import os
import threading
from flask import Flask, request, jsonify

from review_service import process_review
from utils import log_info, log_error

app = Flask(__name__)

# Webhook secret from GitHub App settings
WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "").encode()


def verify_signature(payload_body: bytes, signature_header: str) -> bool:
    """Verify GitHub webhook signature using HMAC-SHA256."""
    if not WEBHOOK_SECRET:
        log_error("GITHUB_WEBHOOK_SECRET not set")
        return False
    
    hash_object = hmac.new(WEBHOOK_SECRET, msg=payload_body, digestmod=hashlib.sha256)
    expected_signature = "sha256=" + hash_object.hexdigest()
    
    return hmac.compare_digest(expected_signature, signature_header)


@app.route("/webhook", methods=["POST"])
def handle_webhook():
    """Handle incoming GitHub webhooks."""
    # Verify signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(request.data, signature):
        log_error("Invalid webhook signature")
        return jsonify({"error": "Invalid signature"}), 401
    
    # Parse event
    event_type = request.headers.get("X-GitHub-Event", "")
    payload = request.json
    
    log_info(f"Received {event_type} event")
    
    # Filter events we care about
    if event_type == "pull_request":
        action = payload.get("action", "")
        if action in ["opened", "synchronize", "reopened"]:
            # Process async to respond quickly
            thread = threading.Thread(target=process_review, args=(payload,))
            thread.start()
            return jsonify({"status": "queued"}), 200
        else:
            return jsonify({"status": "ignored", "reason": f"action={action}"}), 200
    
    elif event_type == "push":
        ref = payload.get("ref", "")
        # Only review main branches
        if ref in ["refs/heads/main", "refs/heads/master", "refs/heads/develop"]:
            thread = threading.Thread(target=process_review, args=(payload,))
            thread.start()
            return jsonify({"status": "queued"}), 200
        else:
            return jsonify({"status": "ignored", "reason": f"ref={ref}"}), 200
    
    elif event_type == "ping":
        return jsonify({"status": "pong"}), 200
    
    else:
        return jsonify({"status": "ignored", "reason": f"event={event_type}"}), 200


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy"}), 200


@app.route("/", methods=["GET"])
def index():
    """Root endpoint."""
    return jsonify({
        "name": "Jules Code Review Bot",
        "status": "running",
        "endpoints": {
            "webhook": "/webhook",
            "health": "/health"
        }
    }), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
