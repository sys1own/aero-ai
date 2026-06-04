"""
Multi-provider LLM client (OpenRouter / Groq / Gemini)
======================================================

A small, dependency-free orchestration client used by ``evolve_loop.py`` to ask
an LLM for build-schedule tuning proposals.

Design / scope notes
--------------------
* Standard library only (``urllib``) — no SDKs to install.
* One API key per provider, read from the environment
  (``OPENROUTER_API_KEY`` / ``GROQ_API_KEY`` / ``GEMINI_API_KEY``). Only
  providers whose key is present are enabled.
* **Failover is for resilience.** On a 429 / timeout / transient error the
  client falls through the chain OpenRouter -> Groq -> Gemini. It *honors*
  ``Retry-After`` and backs off — it does not attempt to circumvent any single
  provider's rate limiting. Round-robin selection simply spreads requests over
  the providers you already hold credentials for.
* Keys are never logged or persisted.

Quick check (no network, no tokens spent)::

    python aero_mesh_core/llm_client.py        # prints which providers are configured
"""

import json
import os
import random
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


# ── Provider registry (canonical failover order) ───────────────────────────

@dataclass(frozen=True)
class ProviderSpec:
    name: str
    env_key: str
    kind: str            # "openai" (chat/completions schema) or "gemini"
    endpoint: str
    model_env: str
    default_model: str


_PROVIDERS = [
    ProviderSpec(
        name="openrouter", env_key="OPENROUTER_API_KEY", kind="openai",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        model_env="OPENROUTER_MODEL", default_model="openai/gpt-4o-mini",
    ),
    ProviderSpec(
        name="groq", env_key="GROQ_API_KEY", kind="openai",
        endpoint="https://api.groq.com/openai/v1/chat/completions",
        model_env="GROQ_MODEL", default_model="llama-3.3-70b-versatile",
    ),
    ProviderSpec(
        name="gemini", env_key="GEMINI_API_KEY", kind="gemini",
        endpoint="https://generativelanguage.googleapis.com/v1beta/models",
        model_env="GEMINI_MODEL", default_model="gemini-1.5-flash",
    ),
]


class LLMError(Exception):
    """All providers failed, or a non-recoverable error occurred."""


class LLMUnavailable(LLMError):
    """No provider is configured (no API keys in the environment)."""


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str


# ── Internal error classification ──────────────────────────────────────────

class _Transient(Exception):
    """Retryable: 429 / 5xx / timeout / connection error. Carries an optional
    suggested wait (seconds)."""
    def __init__(self, msg, retry_after=None):
        super().__init__(msg)
        self.retry_after = retry_after


class _Permanent(Exception):
    """Not retryable on this provider (e.g. 400/401) — fail over instead."""


class LLMClient:
    def __init__(self, timeout=60, max_retries_per_provider=2,
                 selection="round_robin", backoff_cap=30.0, seed=None):
        self.timeout = timeout
        self.max_retries = max(0, max_retries_per_provider)
        self.selection = selection
        self.backoff_cap = backoff_cap
        self._rng = random.Random(seed)
        self._rr_index = 0
        self._providers = [p for p in _PROVIDERS if os.environ.get(p.env_key)]
        if self._providers:
            print(f"[llm] configured providers: "
                  f"{', '.join(p.name for p in self._providers)}")
        else:
            print("[llm] WARNING: no provider API keys found in environment")

    def available(self):
        return [p.name for p in self._providers]

    # -- selection / failover ------------------------------------------------

    def _attempt_order(self):
        """Load-balanced primary + canonical failover tail."""
        provs = list(self._providers)
        if not provs:
            return []
        if self.selection == "random":
            self._rng.shuffle(provs)
            return provs
        # round-robin: rotate the canonical list so the start advances per call
        start = self._rr_index % len(provs)
        self._rr_index += 1
        return provs[start:] + provs[:start]

    def complete(self, prompt, system=None, max_tokens=1024, temperature=0.2):
        """Return an LLMResponse, failing over across providers as needed."""
        order = self._attempt_order()
        if not order:
            raise LLMUnavailable("no LLM providers configured (set *_API_KEY)")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        primary = order[0].name
        print(f"[llm] primary selection: {primary} "
              f"(load-balanced; failover -> {[p.name for p in order[1:]]})")

        last_err = None
        for spec in order:
            model = os.environ.get(spec.model_env, spec.default_model)
            for attempt in range(self.max_retries + 1):
                try:
                    text = self._call(spec, model, messages, max_tokens, temperature)
                    return LLMResponse(text=text, provider=spec.name, model=model)
                except _Transient as exc:
                    last_err = exc
                    if attempt < self.max_retries:
                        wait = exc.retry_after if exc.retry_after is not None \
                            else min(self.backoff_cap, 2.0 ** attempt)
                        wait = min(wait, self.backoff_cap)
                        print(f"[llm] {spec.name} transient ({exc}); "
                              f"retry {attempt + 1}/{self.max_retries} in {wait:.1f}s")
                        time.sleep(wait)
                        continue
                    print(f"[llm] {spec.name} exhausted retries ({exc}) -> failing over")
                    break
                except _Permanent as exc:
                    last_err = exc
                    print(f"[llm] {spec.name} non-recoverable ({exc}) -> failing over")
                    break
        raise LLMError(f"all providers failed; last error: {last_err}")

    # -- transport -----------------------------------------------------------

    def _call(self, spec, model, messages, max_tokens, temperature):
        url, headers, body = self._build_request(spec, model, messages,
                                                 max_tokens, temperature)
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"),
            headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            self._raise_for_http(spec, exc)
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            raise _Transient(f"connection error: {exc}")
        return self._parse_response(spec, data)

    @staticmethod
    def _raise_for_http(spec, exc):
        retry_after = None
        ra = exc.headers.get("Retry-After") if exc.headers else None
        if ra:
            try:
                retry_after = float(ra)
            except ValueError:
                retry_after = None
        if exc.code == 429:
            raise _Transient(f"HTTP 429 rate limited", retry_after=retry_after)
        if 500 <= exc.code < 600:
            raise _Transient(f"HTTP {exc.code} server error")
        # 400/401/403/404 etc. — bad key/model/request: fail over, don't retry.
        raise _Permanent(f"HTTP {exc.code}")

    @staticmethod
    def _build_request(spec, model, messages, max_tokens, temperature):
        key = os.environ[spec.env_key]
        if spec.kind == "openai":
            url = spec.endpoint
            headers = {"Authorization": f"Bearer {key}",
                       "Content-Type": "application/json"}
            body = {"model": model, "messages": messages,
                    "max_tokens": max_tokens, "temperature": temperature}
            return url, headers, body

        # gemini: key in query string, different body schema
        url = f"{spec.endpoint}/{model}:generateContent?key={key}"
        headers = {"Content-Type": "application/json"}
        contents, system_txt = [], None
        for m in messages:
            if m["role"] == "system":
                system_txt = m["content"]
            else:
                role = "model" if m["role"] == "assistant" else "user"
                contents.append({"role": role, "parts": [{"text": m["content"]}]})
        body = {"contents": contents,
                "generationConfig": {"maxOutputTokens": max_tokens,
                                     "temperature": temperature}}
        if system_txt:
            body["systemInstruction"] = {"parts": [{"text": system_txt}]}
        return url, headers, body

    @staticmethod
    def _parse_response(spec, data):
        try:
            if spec.kind == "openai":
                return data["choices"][0]["message"]["content"]
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise _Permanent(f"unexpected response shape: {exc}")


if __name__ == "__main__":
    # Config check only — no request is sent, no tokens are spent.
    client = LLMClient()
    names = client.available()
    print(f"[llm] {len(names)} provider(s) ready: {names or '(none)'}")
    sys.exit(0 if names else 1)
