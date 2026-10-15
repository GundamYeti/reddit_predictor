"""Model backends that return JSON matching a schema.

ollama (default): free and local, e.g. phi3:mini. Slow on a CPU and less
    accurate, which is fine because you review what it finds.
claude: much better at sarcasm and political nuance. Needs the anthropic
    package plus an API key (ANTHROPIC_API_KEY) or `ant auth login`. Costs money.

Pick one with PREDICTOR_LLM=ollama|claude, or the --llm flag.
"""

import json
import os
import time
import urllib.request

from predictor.activity_log import log_call


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
        start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.load(resp)
        except Exception as e:
            log_call("reddit_predictor", "ollama", self.model, time.monotonic() - start,
                     ok=False, error=e, preview=prompt)
            raise
        # Ollama durations are in nanoseconds.
        eval_s = (data.get("eval_duration") or 0) / 1e9
        log_call("reddit_predictor", "ollama", self.model, time.monotonic() - start, preview=prompt,
                 input_tokens=data.get("prompt_eval_count"), output_tokens=data.get("eval_count"),
                 tokens_per_s=round(data["eval_count"] / eval_s, 1) if eval_s and data.get("eval_count") else None,
                 load_s=round((data.get("load_duration") or 0) / 1e9, 1) or None)
        return json.loads(data["response"])


# Dollars per million tokens (input, output), for the running cost estimate.
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-opus-5": (5.0, 25.0), "claude-sonnet-5-5": (2.0, 10.0),
          "claude-sonnet-5": (2.0, 10.0), "claude-haiku-4-5": (1.0, 5.0)}


class ClaudeBackend:
    def __init__(self, model=None):
        try:
            import anthropic
        except ImportError:
            raise SystemExit("The claude backend needs the anthropic package: pip install anthropic")
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("PREDICTOR_CLAUDE_MODEL", "claude-opus-5-5")
        self.name = f"claude:{self.model}"
        self.input_tokens = self.output_tokens = 0
        self.cache_read_tokens = self.cache_write_tokens = 0

    def _dollars(self, inp_tokens, out_tokens, read_tokens, write_tokens):
        if self.model not in PRICES:
            return None
        inp, out = PRICES[self.model]
        # Cache reads cost a tenth of normal input; writing the cache costs 1.25x.
        return (inp_tokens * inp + out_tokens * out + read_tokens * inp * 0.1 + write_tokens * inp * 1.25) / 1e6

    def cost(self):
        """Estimated dollars spent so far this run, or None for an unknown model."""
        return self._dollars(self.input_tokens, self.output_tokens, self.cache_read_tokens, self.cache_write_tokens)

    def complete_json(self, system, prompt, schema):
        start = time.monotonic()
        try:
            output_config = {"format": {"type": "json_schema", "schema": schema}}
            if not self.model.startswith("claude-haiku"):  # Haiku 4.5 doesn't take an effort setting
                # Low effort keeps per-comment cost down; raise it if tagging quality disappoints.
                output_config["effort"] = os.environ.get("PREDICTOR_CLAUDE_EFFORT", "low")
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8000,
                # The instructions are identical on every call, so cache them: later calls
                # read them at a tenth of the price. (Haiku 4.5 needs 4,096+ tokens to cache,
                # so for it this is a no-op.)
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": prompt}],
                output_config=output_config,
            )
        except Exception as e:
            log_call("reddit_predictor", "claude", self.model, time.monotonic() - start,
                     ok=False, error=e, preview=prompt)
            raise
        u = response.usage
        read, write = u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0
        self.input_tokens += u.input_tokens
        self.output_tokens += u.output_tokens
        self.cache_read_tokens += read
        self.cache_write_tokens += write
        dollars = self._dollars(u.input_tokens, u.output_tokens, read, write)
        log_call("reddit_predictor", "claude", self.model, time.monotonic() - start, preview=prompt,
                 ok=response.stop_reason != "refusal",
                 error="refused" if response.stop_reason == "refusal" else None,
                 input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                 cache_read_tokens=read or None, cache_write_tokens=write or None,
                 cost_usd=round(dollars, 5) if dollars is not None else None)
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
