"""Provider-fallback layer for the rerank stage (the only place an LLM is used).

Free tiers shift, so providers are tried in order and any failure falls through to the next.
Keys come from env: GEMINI_API_KEY, MISTRAL_API_KEY, GROQ_API_KEY.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Callable

import httpx


class LLMError(RuntimeError):
    pass


@dataclass
class Provider:
    name: str
    env_key: str
    call: Callable[[httpx.Client, str, str, float], str]  # (client, api_key, prompt, timeout) -> text

    def available(self) -> bool:
        return bool(os.environ.get(self.env_key))


def _gemini(c: httpx.Client, key: str, prompt: str, timeout: float) -> str:
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
    r = c.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key},
        json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0}},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _openai_compat(url: str, model_env: str, default_model: str):
    def call(c: httpx.Client, key: str, prompt: str, timeout: float) -> str:
        r = c.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": os.environ.get(model_env, default_model),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    return call


DEFAULT_PROVIDERS = [
    Provider("gemini", "GEMINI_API_KEY", _gemini),
    Provider("mistral", "MISTRAL_API_KEY", _openai_compat("https://api.mistral.ai/v1/chat/completions", "MISTRAL_MODEL", "mistral-small-latest")),
    Provider("groq", "GROQ_API_KEY", _openai_compat("https://api.groq.com/openai/v1/chat/completions", "GROQ_MODEL", "llama-3.3-70b-versatile")),
]


def parse_json(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    return json.loads(text)


class FallbackLLM:
    def __init__(self, providers: list[Provider] | None = None, timeout: float = 30.0, client: httpx.Client | None = None):
        self.providers = [p for p in (providers or DEFAULT_PROVIDERS) if p.available()]
        self.timeout = timeout
        self.client = client or httpx.Client()
        self.last_provider: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.providers)

    def complete_json(self, prompt: str):
        errors = []
        for p in self.providers:
            try:
                out = parse_json(p.call(self.client, os.environ[p.env_key], prompt, self.timeout))
                self.last_provider = p.name
                return out
            except Exception as e:  # rate limit, quota change, bad JSON, network: try the next provider
                errors.append(f"{p.name}: {type(e).__name__}: {e}")
        raise LLMError("all providers failed: " + "; ".join(errors) if errors else "no LLM provider configured")
