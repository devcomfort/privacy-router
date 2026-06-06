"""API Key management routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select

from db.models import ApiKey, Provider
from db.session import get_session
from server.api.auth import create_api_key, require_auth
from server.api.main import app


class KeyCreate(BaseModel):
    provider_id: str
    name: str = Field(default="default")


class KeyOut(BaseModel):
    id: str
    provider_id: str
    name: str
    prefix: str
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class KeyCreated(BaseModel):
    id: str
    provider_id: str
    name: str
    api_key: str
    message: str = "Store this API key securely. It will not be shown again."


@app.get("/api/v1/keys", response_model=list[KeyOut])
def list_keys(_auth: str = Depends(require_auth)):
    session = get_session()
    try:
        keys = session.exec(select(ApiKey).order_by(ApiKey.created_at.desc())).all()
        return [KeyOut.model_validate(k) for k in keys]
    finally:
        session.close()


@app.post("/api/v1/keys", response_model=KeyCreated, status_code=201)
def create_key(body: KeyCreate, _auth: str = Depends(require_auth)):
    session = get_session()
    try:
        if not session.get(Provider, body.provider_id):
            raise HTTPException(404, "Provider not found")
        raw, hashed = create_api_key()
        key = ApiKey(
            provider_id=body.provider_id,
            name=body.name,
            key_hash=hashed,
            prefix=raw[:11],
        )
        session.add(key)
        session.commit()
        session.refresh(key)
        return KeyCreated(
            id=key.id,
            provider_id=key.provider_id,
            name=key.name,
            api_key=raw,
        )
    finally:
        session.close()


@app.post("/api/v1/keys/{key_id}/rotate", response_model=KeyCreated)
def rotate_key(key_id: str, _auth: str = Depends(require_auth)):
    session = get_session()
    try:
        old = session.get(ApiKey, key_id)
        if not old:
            raise HTTPException(404, "Key not found")
        raw, hashed = create_api_key()
        new_key = ApiKey(
            provider_id=old.provider_id,
            name=f"{old.name}-rotated",
            key_hash=hashed,
            prefix=raw[:11],
        )
        session.add(new_key)
        old.is_active = False
        session.add(old)
        session.commit()
        session.refresh(new_key)
        return KeyCreated(
            id=new_key.id,
            provider_id=new_key.provider_id,
            name=new_key.name,
            api_key=raw,
        )
    finally:
        session.close()


@app.delete("/api/v1/keys/{key_id}", status_code=204)
def revoke_key(key_id: str, _auth: str = Depends(require_auth)):
    session = get_session()
    try:
        key = session.get(ApiKey, key_id)
        if not key:
            raise HTTPException(404, "Key not found")
        key.is_active = False
        session.add(key)
        session.commit()
    finally:
        session.close()
