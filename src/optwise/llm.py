"""OpenRouter client: structured output, one retry on transient failure, a model fallback list.

Only transient failures are retried (HTTP 429/5xx, network, timeout, empty or non-JSON content).
A validator failure is the caller's business and is never retried here (DESIGN #12).
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMUnavailable(Exception):
    """Every model in the list failed transiently, or no key is set. Callers fall back to code."""


def models(env_var: str, default: str) -> list[str]:
    # Pin exact versions; never "~...-latest" aliases, which change under you without passing the gates.
    return [m.strip() for m in os.environ.get(env_var, default).split(",") if m.strip()]


def api_key() -> str:
    if key := os.environ.get("OPENROUTER_API_KEY"):
        return key
    env = Path(__file__).parents[2] / ".env"
    for line in env.read_text().splitlines() if env.exists() else ():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise LLMUnavailable("OPENROUTER_API_KEY not set (env or .env)")


def _call(model: str, system: str, user: str, schema: dict, max_tokens: int, timeout: float) -> tuple[dict, dict]:
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_schema", "json_schema": schema},
        "temperature": 0,
        "max_tokens": max_tokens,
        "usage": {"include": True},
    }
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.load(r)
    usage = resp.get("usage", {})
    return json.loads(resp["choices"][0]["message"]["content"]), usage  # None/garbage content raises: transient


def chat_json(model_list: list[str], system: str, user: str, schema: dict,
              max_tokens: int = 2000, timeout: float = 20) -> tuple[dict, dict]:
    """Return (parsed JSON, usage incl. model, attempts, cost). Raises LLMUnavailable when all attempts fail."""
    errors, cost = [], 0.0
    for model in model_list:
        for _ in range(2):  # one retry per model
            try:
                out, usage = _call(model, system, user, schema, max_tokens, timeout)
                cost += usage.get("cost", 0)
                return out, {**usage, "cost": cost, "model": model, "attempts": len(errors) + 1}
            except urllib.error.HTTPError as e:
                errors.append(f"{model}: HTTP {e.code}")
                if e.code not in (408, 429) and e.code < 500:
                    break  # 4xx is our bug or a bad model id: retrying will not help
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, TypeError, KeyError, IndexError) as e:
                errors.append(f"{model}: {type(e).__name__}")
    raise LLMUnavailable("; ".join(errors))
