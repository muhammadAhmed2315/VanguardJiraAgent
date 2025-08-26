import json
from typing import Dict, List
from flask import Flask, request, jsonify, Response, stream_with_context

from MCPClient import MCPClient
from utils import replace_iso8601_with_relative

# -------------------- Flask app --------------------
REMOTE_MCP_SERVER_URL = "https://mcp.atlassian.com/v1/sse"

app = Flask(__name__)
mcp_client = MCPClient(REMOTE_MCP_SERVER_URL)
mcp_client.start()


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"}), 200


@app.route("/mcp", methods=["POST"])
def mcp():
    """
    Stream MCP processing as NDJSON (newline-delimited JSON).
    Each tool start event is yielded immediately, followed by a final output object.
    """
    data = request.get_json(force=True, silent=True) or {}

    user_input: str = data.get("input", "")
    history: List[Dict[str, str]] = data.get("history", [])

    if not user_input:
        return jsonify({"error": "Missing 'input'"}), 400

    @stream_with_context
    def generator():
        for line in mcp_client.stream(user_input, history):
            try:
                obj = json.loads(line)
                if obj.get("type") == "final" and "output" in obj:
                    # apply post-processing to final output only
                    obj["output"] = replace_iso8601_with_relative(obj["output"])
                    yield json.dumps(obj) + "\n"
                else:
                    yield line
            except Exception:
                # If a line wasn't JSON, just pass it through
                yield line

    # NOTE: using application/json for compatibility; clients should parse NDJSON lines.
    return Response(generator(), mimetype="application/json")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
