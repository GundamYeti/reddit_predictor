"""
activity_log.py — append one line per model call to the shared AI activity log.

~/ai-monitor reads this file to show which project called which model, how
long it took and how many tokens it used. Each project keeps its own copy of
this file (no shared package to install); keep the copies identical.

The log is JSON Lines at ~/.local/share/ai-activity/calls.jsonl, or wherever
AI_ACTIVITY_LOG points (tests set it to /dev/null).
"""

import json
import os
from datetime import datetime
from pathlib import Path

DEFAULT_PATH = Path.home() / ".local" / "share" / "ai-activity" / "calls.jsonl"
PREVIEW_CHARS = 160


def log_path():
    return Path(os.environ.get("AI_ACTIVITY_LOG") or DEFAULT_PATH)


def log_call(project, backend, model, duration_s, ok=True, error=None, preview=None, **fields):
    """Record one finished model call. Never raises: logging must not break a call.

    fields: any extra numbers worth showing, e.g. input_tokens, output_tokens,
    tokens_per_s, load_s, cost_usd, served_by, source. None values are dropped.
    """
    record = {
        # When the call finished; the monitor matches this against Ollama's own log.
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "project": project,
        "backend": backend,
        "model": model,
        "duration_s": round(duration_s, 2),
        "ok": ok,
    }
    if error:
        record["error"] = str(error)[:300]
    if preview:
        record["preview"] = " ".join(str(preview).split())[:PREVIEW_CHARS]
    record.update({k: v for k, v in fields.items() if v is not None})
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass
