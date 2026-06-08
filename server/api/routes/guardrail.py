"""Privacy Router — LiteLLM Generic Guardrail API endpoint.

Implements the ``POST /api/v1/guardrail`` route consumed by LiteLLM's
``generic_guardrail_api`` guardrail plugin.  When ``input_type`` is
``"request"`` each text is run through the full Privacy Router pipeline
(Extractor → Judge → Router) and the response tells LiteLLM whether
to block, intervene (mask), or pass through.

References
----------
* LiteLLM Generic Guardrail: https://docs.litellm.ai/docs/proxy/guardrails/generic_guardrail_api
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from agents.masker import Masker
from agents.router import PrivacyRouter
from server.api.auth import require_auth
from server.api.main import app


@app.post("/api/v1/guardrail")
async def guardrail(request: Request, _auth: str = Depends(require_auth)) -> JSONResponse:
    """LiteLLM Generic Guardrail API endpoint.

    Request body (``GenericGuardrailAPIRequest``)::

        {
            "texts": ["array of extracted text strings"],
            "structured_messages": [...],
            "input_type": "request" | "response",
            "request_data": {"user_api_key_hash": "..."}
        }

    Response body::

        {"decision": "NONE"}
        {"decision": "BLOCKED"}
        {"decision": "GUARDRAIL_INTERVENED", "modified_texts": [...]}
    """
    body: dict[str, Any] = await request.json()

    input_type: str = body.get("input_type", "request")
    texts: list[str] = body.get("texts", [])

    # Responses pass through unmodified.
    if input_type == "response":
        return JSONResponse({"decision": "NONE"})

    # Nothing to check.
    if not texts:
        return JSONResponse({"decision": "NONE"})

    router = PrivacyRouter()
    masker = Masker()
    modified_texts: list[str] = []
    any_masked = False

    for text in texts:
        pipeline = router.process(text)

        # ── Block ──────────────────────────────────────────────────────
        if pipeline.judgment.policy_action == "block":
            return JSONResponse({"decision": "BLOCKED"})

        # ── Mask ───────────────────────────────────────────────────────
        if pipeline.route.requires_masking:
            records_dict = [r.model_dump() for r in pipeline.records]
            mask_result = masker.mask(text, records_dict)
            modified_texts.append(mask_result.masked_text)
            any_masked = True
        else:
            modified_texts.append(text)

    if any_masked:
        return JSONResponse({
            "decision": "GUARDRAIL_INTERVENED",
            "modified_texts": modified_texts,
        })

    return JSONResponse({"decision": "NONE"})
