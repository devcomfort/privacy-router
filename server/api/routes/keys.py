"""API Key management routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import select

from db import ApiKey, get_session
from server.api import app, create_api_key, require_admin_auth


class KeyCreate(BaseModel):
    name: str = Field(default="default")


class KeyUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None


class BulkKeyAction(BaseModel):
    ids: list[str]


class BulkKeyToggle(BaseModel):
    ids: list[str]
    is_active: bool


class BulkActionResult(BaseModel):
    updated: int
    ids: list[str]
    errors: list[str] = Field(default_factory=list)


class KeyOut(BaseModel):
    id: str
    name: str
    prefix: str
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KeyCreated(BaseModel):
    id: str
    name: str
    api_key: str
    message: str = "Store this API key securely. It will not be shown again."


@app.get("/api/v1/keys", response_model=list[KeyOut])
def list_keys(_admin: str = Depends(require_admin_auth)):
    session = get_session()
    try:
        keys = session.exec(select(ApiKey).order_by(ApiKey.created_at.desc())).all()
        return [KeyOut.model_validate(k) for k in keys]
    finally:
        session.close()


@app.post("/api/v1/keys", response_model=KeyCreated, status_code=201)
def create_key(body: KeyCreate, _admin: str = Depends(require_admin_auth)):
    session = get_session()
    try:
        raw, hashed = create_api_key()
        key = ApiKey(
            name=body.name,
            key_hash=hashed,
            prefix=raw[:11],
        )
        session.add(key)
        session.commit()
        session.refresh(key)
        return KeyCreated(
            id=key.id,
            name=key.name,
            api_key=raw,
        )
    finally:
        session.close()


@app.post("/api/v1/keys/{key_id}/renew", response_model=KeyCreated)
def renew_key(key_id: str, _admin: str = Depends(require_admin_auth)):
    session = get_session()
    try:
        old = session.get(ApiKey, key_id)
        if not old:
            raise HTTPException(404, "Key not found")
        raw, hashed = create_api_key()
        new_key = ApiKey(
            name=f"{old.name}-renewed",
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
            name=new_key.name,
            api_key=raw,
        )
    finally:
        session.close()


@app.patch("/api/v1/keys/{key_id}", response_model=KeyOut)
def update_key(
    key_id: str,
    body: KeyUpdate,
    _admin: str = Depends(require_admin_auth),
):
    session = get_session()
    try:
        key = session.get(ApiKey, key_id)
        if not key:
            raise HTTPException(404, "Key not found")
        if body.name is not None:
            key.name = body.name
        if body.is_active is not None:
            key.is_active = body.is_active
        session.add(key)
        session.commit()
        session.refresh(key)
        return KeyOut.model_validate(key)
    finally:
        session.close()


@app.post("/api/v1/keys/bulk-toggle", response_model=BulkActionResult)
def bulk_toggle(
    body: BulkKeyToggle,
    _admin: str = Depends(require_admin_auth),
):
    session = get_session()
    try:
        updated_ids = []
        errors = []
        for key_id in body.ids:
            key = session.get(ApiKey, key_id)
            if key:
                key.is_active = body.is_active
                session.add(key)
                updated_ids.append(key_id)
            else:
                errors.append(f"Key not found: {key_id}")
        session.commit()
        return BulkActionResult(updated=len(updated_ids), ids=updated_ids, errors=errors)
    finally:
        session.close()


@app.post("/api/v1/keys/bulk-delete", response_model=BulkActionResult)
def bulk_delete(
    body: BulkKeyAction,
    _admin: str = Depends(require_admin_auth),
):
    session = get_session()
    try:
        deleted_ids = []
        errors = []
        for key_id in body.ids:
            key = session.get(ApiKey, key_id)
            if key:
                session.delete(key)
                deleted_ids.append(key_id)
            else:
                errors.append(f"Key not found: {key_id}")
        session.commit()
        return BulkActionResult(updated=len(deleted_ids), ids=deleted_ids, errors=errors)
    finally:
        session.close()


@app.delete("/api/v1/keys/{key_id}", status_code=204)
def revoke_key(key_id: str, _admin: str = Depends(require_admin_auth)):
    session = get_session()
    try:
        key = session.get(ApiKey, key_id)
        if not key:
            raise HTTPException(404, "Key not found")
        session.delete(key)
        session.commit()
    finally:
        session.close()
