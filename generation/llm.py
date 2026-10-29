"""Model calls via LiteLLM, so any provider works by model name (e.g. "anthropic/<model>",
"openai/<model>", "gemini/<model>"). Keys come from the usual env vars (ANTHROPIC_API_KEY etc.).

Every call returns (result, meta) where meta has model, template version, tokens, cost, latency.
Pin exact model versions in the round config; a model change means re-running the evals.
"""
from __future__ import annotations

import hashlib
import json
import time
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from schema.models import Brief, ParsedProfile

ROOT = Path(__file__).resolve().parents[1]
ENV = Environment(loader=FileSystemLoader(ROOT / "prompts"), undefined=StrictUndefined, trim_blocks=True)


@lru_cache
def template_version(name: str) -> str:
    return hashlib.sha1((ROOT / "prompts" / name).read_bytes()).hexdigest()[:8]


def _json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def call(model: str, prompt: str, template: str, temperature: float = 0.2, max_tokens: int = 2000) -> tuple[dict, dict]:
    import litellm  # imported lazily so the rest of the harness runs without it

    t0 = time.time()
    resp = litellm.completion(model=model, messages=[{"role": "user", "content": prompt}],
                              temperature=temperature, max_tokens=max_tokens)
    text = resp.choices[0].message.content
    try:
        cost = litellm.completion_cost(completion_response=resp)
    except Exception:
        cost = None
    meta = {"model": model, "template": template, "template_version": template_version(template),
            "input_tokens": resp.usage.prompt_tokens, "output_tokens": resp.usage.completion_tokens,
            "cost_usd": cost, "latency_s": round(time.time() - t0, 2), "raw": text}
    return _json(text), meta


def parse_profile(text: str, model: str) -> tuple[ParsedProfile, dict]:
    prompt = ENV.get_template("parser.j2").render(text=text)
    data, meta = call(model, prompt, "parser.j2", temperature=0.0, max_tokens=400)
    meta.pop("raw", None)
    return ParsedProfile(**data), meta


def generate_recipe(brief: Brief, model: str, template: str, catalogue_keys: list[str]) -> tuple[dict, dict]:
    name = f"recipe_{template}.j2"
    prompt = ENV.get_template(name).render(brief=brief, catalogue_keys=catalogue_keys)
    return call(model, prompt, name, temperature=0.4)


def critique(brief: Brief, recipe_json: dict, model: str) -> tuple[dict, dict]:
    prompt = ENV.get_template("critic.j2").render(brief=brief, recipe_json=json.dumps(recipe_json, indent=1))
    return call(model, prompt, "critic.j2", temperature=0.0, max_tokens=800)
