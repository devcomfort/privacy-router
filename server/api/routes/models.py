"""Model registry + agent config routes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from config import ModelSpec
from db import Model, ProfileAgent, Provider, get_session
from server.api import app, require_admin_auth
from server.config import config_write_lock, invalidate_config_cache


class ModelCreate(BaseModel):
    model_id: str = Field(...)
    provider_id: str = Field(default="openrouter")
    display_name: str | None = None
    params: str | None = None
    location: str = Field(default="external")
    tier: Literal["small", "middle", "large"] = "small"
    cost_per_1m_tokens: float = 0.0
    api_base_override: str | None = None


class ModelOut(BaseModel):
    id: str
    model_id: str
    provider_id: str
    display_name: str | None
    params: str | None
    location: str
    tier: Literal["small", "middle", "large"]
    cost_per_1m_tokens: float
    api_base_override: str | None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


@app.get("/api/v1/models", response_model=list[ModelOut])
def list_models(tier: str | None = None, _admin: str = Depends(require_admin_auth)):
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
def register_model(
    body: ModelCreate,
    _admin: str = Depends(require_admin_auth),
):
    with config_write_lock():
        session = get_session()
        try:
            existing = session.exec(select(Model).where(Model.model_id == body.model_id)).first()
            if existing is not None:
                raise HTTPException(409, f"Model '{body.model_id}' is already registered")

            provider = session.get(Provider, body.provider_id)
            if provider is None:
                raise HTTPException(422, f"Provider '{body.provider_id}' is not registered")

            expected_provider_id = body.model_id.split("/", 1)[0]
            if expected_provider_id != body.provider_id:
                raise HTTPException(
                    422,
                    f"provider_id must match the model_id prefix ('{expected_provider_id}')",
                )

            effective_api_base = body.api_base_override or provider.api_base
            try:
                spec = ModelSpec(
                    id=body.model_id,
                    api_base=effective_api_base,
                    location=body.location,
                    tier=body.tier,
                    cost_per_1m_tokens=body.cost_per_1m_tokens,
                )
            except ValidationError as exc:
                raise HTTPException(422, str(exc)) from exc

            model = Model(
                model_id=spec.id,
                provider_id=body.provider_id,
                display_name=body.display_name,
                params=body.params,
                location=spec.location,
                tier=spec.tier,
                cost_per_1m_tokens=spec.cost_per_1m_tokens,
                api_base_override=body.api_base_override,
            )
            session.add(model)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise HTTPException(409, f"Model '{body.model_id}' is already registered") from exc
            session.refresh(model)
            invalidate_config_cache()
            return ModelOut.model_validate(model)
        finally:
            session.close()


@app.delete("/api/v1/models/{model_record_id}", status_code=204)
def remove_model(
    model_record_id: str,
    _admin: str = Depends(require_admin_auth),
):
    with config_write_lock():
        session = get_session()
        try:
            model = session.get(Model, model_record_id)
            if model is None:
                raise HTTPException(404, "Not found")

            binding = session.exec(select(ProfileAgent).where(ProfileAgent.model_id == model.model_id)).first()
            if binding is not None:
                raise HTTPException(
                    409,
                    f"Model '{model.model_id}' is still bound to profile "
                    f"'{binding.profile_id}' role '{binding.agent_name}'",
                )

            model.is_active = False
            session.add(model)
            session.commit()
            invalidate_config_cache()
        finally:
            session.close()
