"""Model registry + probing routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select

from db.models import AgentConfig, Model, Provider
from db.session import get_session
from server.api.auth import require_auth
from server.api.main import app


class ModelCreate(BaseModel):
    model_id: str = Field(...)
    provider_id: str
    display_name: str | None = None
    tier: str = Field(default="external")
    cost_per_1m_tokens: float = 0.0


class ModelOut(BaseModel):
    id: str
    model_id: str
    provider_id: str
    display_name: str | None
    tier: str
    cost_per_1m_tokens: float
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ProbeRequest(BaseModel):
    provider_id: str


class AgentConfigUpdate(BaseModel):
    agent_name: str = Field(...)
    model_id: str
    temperature: float = 0.0
    max_tokens: int = 4096


@app.get("/api/v1/models", response_model=list[ModelOut])
def list_models(tier: str | None = None, _auth: str = Depends(require_auth)):
    session = get_session()
    try:
        q = select(Model).where(Model.is_active)
        if tier:
            q = q.where(Model.tier == tier)
        models = session.exec(q.order_by(Model.model_id)).all()
        return [ModelOut.model_validate(m) for m in models]
    finally:
        session.close()


@app.post("/api/v1/models", response_model=ModelOut, status_code=201)
def register_model(body: ModelCreate, _auth: str = Depends(require_auth)):
    session = get_session()
    try:
        if not session.get(Provider, body.provider_id):
            raise HTTPException(404, "Provider not found")
        m = Model(
            model_id=body.model_id,
            provider_id=body.provider_id,
            display_name=body.display_name,
            tier=body.tier,
            cost_per_1m_tokens=body.cost_per_1m_tokens,
        )
        session.add(m)
        session.commit()
        session.refresh(m)
        return ModelOut.model_validate(m)
    finally:
        session.close()


@app.delete("/api/v1/models/{model_id}", status_code=204)
def remove_model(model_id: str, _auth: str = Depends(require_auth)):
    session = get_session()
    try:
        m = session.get(Model, model_id)
        if not m:
            raise HTTPException(404, "Not found")
        m.is_active = False
        session.add(m)
        session.commit()
    finally:
        session.close()


@app.post("/api/v1/models/probe")
def probe_models(body: ProbeRequest, _auth: str = Depends(require_auth)) -> dict[str, Any]:
    session = get_session()
    try:
        provider = session.get(Provider, body.provider_id)
        if not provider:
            raise HTTPException(404, "Provider not found")
        return _probe(provider)
    finally:
        session.close()


@app.get("/api/v1/agent-configs")
def get_agent_configs(_auth: str = Depends(require_auth)):
    session = get_session()
    try:
        configs = session.exec(select(AgentConfig)).all()
        return {
            c.agent_name: {
                "model_id": c.model_id,
                "temperature": c.temperature,
                "max_tokens": c.max_tokens,
            }
            for c in configs
        }
    finally:
        session.close()


@app.put("/api/v1/agent-configs")
def update_agent_configs(body: list[AgentConfigUpdate], _auth: str = Depends(require_auth)):
    session = get_session()
    try:
        for entry in body:
            c = session.exec(
                select(AgentConfig).where(AgentConfig.agent_name == entry.agent_name)
            ).first()
            if c:
                c.model_id = entry.model_id
                c.temperature = entry.temperature
                c.max_tokens = entry.max_tokens
                c.updated_at = datetime.utcnow()
            else:
                c = AgentConfig(
                    agent_name=entry.agent_name,
                    model_id=entry.model_id,
                    temperature=entry.temperature,
                    max_tokens=entry.max_tokens,
                )
            session.add(c)
        session.commit()
        return {"status": "ok"}
    finally:
        session.close()


_PROBE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1/models",
    "openai": "https://api.openai.com/v1/models",
}


def _probe(provider: Provider) -> dict[str, Any]:
    if provider.provider_type == "custom" and provider.api_base:
        url = f"{provider.api_base.rstrip('/')}/models"
    elif provider.provider_type in _PROBE_URLS:
        url = _PROBE_URLS[provider.provider_type]
    else:
        return {"models": [], "error": f"Unknown provider type: {provider.provider_type}"}
    headers = {"Authorization": "Bearer sk-placeholder"}
    try:
        resp = httpx.get(url, headers=headers, timeout=10.0)
        if resp.status_code != 200:
            return {"models": [], "error": f"HTTP {resp.status_code}"}
        data = resp.json()
        items = data.get("data", data) if isinstance(data, dict) else data
        return {"models": [item.get("id", "") for item in items if isinstance(item, dict)], "error": None}
    except httpx.ConnectError:
        return {"models": [], "error": "Connection failed — is the server running?"}
    except Exception as exc:
        return {"models": [], "error": str(exc)}
