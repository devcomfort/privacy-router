from __future__ import annotations

import json
from importlib.metadata import version
from typing import Any

from transformers import AutoTokenizer

from probe_common import load_messages


MESSAGES = load_messages()

MODELS = [
    ("HuggingFaceTB/SmolLM2-135M-Instruct", "12fd25f77366fa6b3b4b768ec3050bf629380bac"),
    ("Qwen/Qwen2.5-0.5B-Instruct", "7ae557604adf67be50417f59c2c2f167def9a775"),
    ("mistralai/Mistral-7B-Instruct-v0.2", "63a8b081895390a26e140280378bc85ec8bce07a"),
]
results: dict[str, Any] = {"transformers_version": version("transformers"), "models": {}}
for model_id, revision in MODELS:
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_id, revision=revision, trust_remote_code=False)
        rendered = tokenizer.apply_chat_template(MESSAGES, tokenize=False, add_generation_prompt=True)
        results["models"][model_id] = {
            "requested_revision": revision,
            "resolved_commit": tokenizer.init_kwargs.get("_commit_hash", revision),
            "tokenizer_class": type(tokenizer).__name__,
            "chat_template_present": tokenizer.chat_template is not None,
            "rendered": rendered,
            "rendered_repr": repr(rendered),
        }
    except Exception as exc:
        results["models"][model_id] = {"requested_revision": revision, "error": f"{type(exc).__name__}: {exc}"}

print(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True))
