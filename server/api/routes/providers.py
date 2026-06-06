"""Provider management routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select

from db.models import Provider
from db.session import get_session
from server.api.auth import require_auth
from server.api.main import app


class ProviderCreate(BaseModel):
    name: str
    provider_type: str = Field(...)
    api_key_env: str | None = None
    api_base: str | None = None


class ProviderUpdate(BaseModel):
    name: str | None = None
    api_key_env: str | None = None
    api_base: str | None = None
    is_active: bool | None = None


class ProviderOut(BaseModel):
    id: str
    name: str
    provider_type: str
    api_key_env: str | None
    api_base: str | None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


@app.get("/api/v1/providers", response_model=list[ProviderOut])
def list_providers(_auth: str = Depends(require_auth)):
    session = get_session()
    try:
        providers = session.exec(select(Provider).order_by(Provider.name)).all()
        return [ProviderOut.model_validate(p) for p in providers]
    finally:
        session.close()


@app.get("/api/v1/providers/{provider_id}", response_model=ProviderOut)
def get_provider(provider_id: str, _auth: str = Depends(require_auth)):
    session = get_session()
    try:
        p = session.get(Provider, provider_id)
        if not p:
            raise HTTPException(404, "Not found")
        return ProviderOut.model_validate(p)
    finally:
        session.close()


@app.post("/api/v1/providers", status_code=201)
def create_provider(body: ProviderCreate, _auth: str = Depends(require_auth)):
    session = get_session()
    try:
        p = Provider(
            name=body.name,
            provider_type=body.provider_type,
            api_key_env=body.api_key_env,
            api_base=body.api_base,
        )
        session.add(p)
        session.commit()
        session.refresh(p)
        return {
            "id": p.id,
            "name": p.name,
            "message": "Provider created. Use POST /api/v1/keys to create an API key.",
        }
    finally:
        session.close()


@app.put("/api/v1/providers/{provider_id}", response_model=ProviderOut)
def update_provider(provider_id: str, body: ProviderUpdate, _auth: str = Depends(require_auth)):
    session = get_session()
    try:
        p = session.get(Provider, provider_id)
        if not p:
            raise HTTPException(404, "Not found")
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(p, k, v)
        p.updated_at = datetime.utcnow()
        session.add(p)
        session.commit()
        session.refresh(p)
        return ProviderOut.model_validate(p)
    finally:
        session.close()


@app.delete("/api/v1/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: str, _auth: str = Depends(require_auth)):
    session = get_session()
    try:
        p = session.get(Provider, provider_id)
        if not p:
            raise HTTPException(404, "Not found")
        session.delete(p)
        session.commit()
    finally:
        session.close()
