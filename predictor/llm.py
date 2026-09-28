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
            # num_ctx matches ~/ai-assistant's setting: the two share one Ollama server,
            # and a different value makes it reload the model each time they alternate.
            # 4096 also pushed Ollama to ~4 GB, more than this laptop can spare.
            # num_predict caps the reply; the JSON answer is well under 300 tokens.
            "options": {"temperature": 0, "num_ctx": int(os.environ.get("PREDICTOR_OLLAMA_NUM_CTX", "2048")),
                        "num_predict": 300},
        }).encode()
        req = urllib.request.Request(self.url + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        timeout = float(os.environ.get("PREDICTOR_OLLAMA_TIMEOUT", "300"))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(json.load(resp)["response"])


# Dollars per million tokens (input, output), for the running cost estimate.
PRICES = {"claude-opus-5": (5.0, 25.0), "claude-sonnet-5": (2.0, 10.0), "claude-haiku-4-5": (1.0, 5.0)}


class ClaudeBackend:
    def __init__(self, model=None):
        try:
            import anthropic
        except ImportError:
            raise SystemExit("The claude backend needs the anthropic package: pip install anthropic")
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("PREDICTOR_CLAUDE_MODEL", "claude-opus-5")
        self.name = f"claude:{self.model}"
        self.input_tokens = self.output_tokens = 0

    def cost(self):
        """Estimated dollars spent so far this run, or None for an unknown model."""
        if self.model not in PRICES:
            return None
        inp, out = PRICES[self.model]
        return (self.input_tokens * inp + self.output_tokens * out) / 1e6

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
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens
        if response.stop_reason == "refusal":
            raise RuntimeError("model declined to classify this comment")
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)


def load_dotenv(path=".env"):
    """Read KEY=value lines from .env (git-ignored) without overriding the real environment."""
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip("'\""))
    except FileNotFoundError:
        pass


def get_backend(name=None, model=None):
    load_dotenv()
    name = name or os.environ.get("PREDICTOR_LLM", "ollama")
    if name == "ollama":
        return OllamaBackend(model)
    if name == "claude":
        return ClaudeBackend(model)
    raise SystemExit(f"Unknown LLM backend {name!r}; use ollama or claude")
