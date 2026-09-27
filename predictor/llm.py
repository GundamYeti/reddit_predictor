"""Model backends that return JSON matching a schema.

ollama (default): free and local, e.g. phi3:mini. Slow on a CPU and less
    accurate, which is fine because you review what it finds.
claude: much better at sarcasm and political nuance. Needs the anthropic
    package plus an API key (ANTHROPIC_API_KEY) or `ant auth login`. Costs money.

Pick one with PREDICTOR_LLM=ollama|claude, or the --llm flag.
"""

import json
import os
import urllib.request


class OllamaBackend:
    def __init__(self, model=None, url=None):
        self.model = model or os.environ.get("PREDICTOR_OLLAMA_MODEL", "phi3:mini")
        self.url = (url or os.environ.get("PREDICTOR_OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        self.name = f"ollama:{self.model}"

    def complete_json(self, system, prompt, schema):
        body = json.dumps({
            "model": self.model,
            "system": system,
            "prompt": prompt,
            "format": schema,          # Ollama constrains output to this JSON schema
            "stream": False,
            "options": {"temperature": 0, "num_ctx": 4096},
        }).encode()
        req = urllib.request.Request(self.url + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        timeout = float(os.environ.get("PREDICTOR_OLLAMA_TIMEOUT", "300"))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(json.load(resp)["response"])


class ClaudeBackend:
    def __init__(self, model=None):
        try:
            import anthropic
        except ImportError:
            raise SystemExit("The claude backend needs the anthropic package: pip install anthropic")
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("PREDICTOR_CLAUDE_MODEL", "claude-opus-5")
        self.name = f"claude:{self.model}"

    def complete_json(self, system, prompt, schema):
        response = self.client.messages.create(
            model=self.model,
            max_tokens=8000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            # Low effort keeps per-comment cost down; raise it if tagging quality disappoints.
            output_config={"effort": os.environ.get("PREDICTOR_CLAUDE_EFFORT", "low"),
                           "format": {"type": "json_schema", "schema": schema}},
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("model declined to classify this comment")
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)


def get_backend(name=None, model=None):
    name = name or os.environ.get("PREDICTOR_LLM", "ollama")
    if name == "ollama":
        return OllamaBackend(model)
    if name == "claude":
        return ClaudeBackend(model)
    raise SystemExit(f"Unknown LLM backend {name!r}; use ollama or claude")
