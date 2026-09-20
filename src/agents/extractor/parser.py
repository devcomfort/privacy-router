"""Shared parser contract and native detector payload helpers."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from .schemas import ConfidentialityJudgment, NecessityJudgment


class ParsedEntity(BaseModel):
    """Backend-neutral candidate before identity and offset reconciliation."""

    tag: str = Field(..., min_length=1)
    kind: Literal["contextual", "structural"]
    native_label: str | None = None
    span: str = Field(..., min_length=1)
    offsets: tuple[int, int] | None = None
    confidentiality: ConfidentialityJudgment
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    detection_method: Literal["regex", "ner", "token_classifier", "llm", "hybrid"]
    native_metadata: dict[str, Any] = Field(default_factory=dict)
    necessity: NecessityJudgment


class DetectorParser(Protocol):
    """Convert one detector's native payload into normalized candidates."""

    def parse(self, raw: object, text: str) -> list[ParsedEntity]:
        """Parse native detector output for the supplied source text."""
        ...


class DetectorParseError(ValueError):
    """Raised when a native detector payload cannot be parsed safely."""


_LABEL_TO_TAG = {
    "EMAIL_ADDRESS": "EMAIL",
    "private_email": "EMAIL",
    "contact.email": "EMAIL",
    "PERSON": "PERSON",
    "private_person": "PERSON",
    "identity.person_name": "PERSON",
    "PHONE_NUMBER": "PHONE",
    "private_phone": "PHONE",
    "contact.phone": "PHONE",
    "ADDRESS": "ADDRESS",
    "private_address": "ADDRESS",
    "contact.address": "ADDRESS",
    "URL": "URL",
    "private_url": "URL",
    "online.url": "URL",
    "DATE_TIME": "DATE",
    "private_date": "DATE",
    "identity.date_of_birth": "DATE_OF_BIRTH",
    "US_SSN": "SSN",
    "SSN": "SSN",
    "identity.ssn": "SSN",
    "NATIONAL_ID": "NATIONAL_ID",
    "identity.national_id": "NATIONAL_ID",
    "PASSPORT": "PASSPORT",
    "US_PASSPORT": "PASSPORT",
    "identity.passport": "PASSPORT",
    "DRIVER_LICENSE": "DRIVERS_LICENSE",
    "US_DRIVER_LICENSE": "DRIVERS_LICENSE",
    "identity.drivers_license": "DRIVERS_LICENSE",
    "TAX_ID": "TAX_ID",
    "US_ITIN": "TAX_ID",
    "identity.tax_id": "TAX_ID",
    "ACCOUNT_NUMBER": "ACCOUNT_NUMBER",
    "account_number": "ACCOUNT_NUMBER",
    "financial.bank_account": "BANK_ACCOUNT",
    "CREDIT_CARD": "CREDIT_CARD",
    "financial.credit_card": "CREDIT_CARD",
    "IBAN_CODE": "IBAN",
    "financial.iban": "IBAN",
    "SWIFT_BIC": "SWIFT_BIC",
    "financial.swift_bic": "SWIFT_BIC",
    "CRYPTO_WALLET": "CRYPTO_WALLET",
    "financial.crypto_wallet": "CRYPTO_WALLET",
    "financial.amount": "AMOUNT",
    "IP_ADDRESS": "IP_ADDRESS",
    "contact.ip_address": "IP_ADDRESS",
    "MAC_ADDRESS": "MAC_ADDRESS",
    "device.mac_address": "MAC_ADDRESS",
    "IMEI": "IMEI",
    "device.imei": "IMEI",
    "device_id": "DEVICE_ID",
    "developer.device_id": "DEVICE_ID",
    "GPS_COORDINATES": "GPS_COORDINATES",
    "location.gps_coordinates": "GPS_COORDINATES",
    "MEDICAL_LICENSE": "MEDICAL_LICENSE",
    "healthcare.medical_record": "MEDICAL_RECORD",
    "healthcare.condition": "HEALTH_CONDITION",
    "healthcare.medication": "MEDICATION",
    "healthcare.health_plan_id": "HEALTH_PLAN_ID",
    "COMPANY_NAME": "COMPANY_NAME",
    "org.company_name": "COMPANY_NAME",
    "RELIGION": "RELIGION",
    "special.religion": "RELIGION",
    "POLITICAL": "POLITICAL",
    "special.political": "POLITICAL",
    "ORIENTATION": "ORIENTATION",
    "special.orientation": "ORIENTATION",
    "HEALTH_STATUS": "HEALTH_STATUS",
    "special.health_status": "HEALTH_STATUS",
    "CASE_NUMBER": "CASE_NUMBER",
    "legal.case_number": "CASE_NUMBER",
    "API_KEY": "API_KEY",
    "credential.api_key": "API_KEY",
    "PRIVATE_KEY": "PRIVATE_KEY",
    "credential.private_key": "PRIVATE_KEY",
    "JWT": "JWT",
    "credential.jwt": "JWT",
    "CONNECTION_STRING": "CONNECTION_STRING",
    "credential.connection_string": "CONNECTION_STRING",
    "PASSWORD": "PASSWORD",
    "credential.password": "PASSWORD",
    "LOGIN_CREDENTIALS": "LOGIN_CREDENTIALS",
    "developer.login_credentials": "LOGIN_CREDENTIALS",
    "USERNAME": "USERNAME",
    "online.username": "USERNAME",
    "SECRET": "SECRET",
    "secret": "SECRET",
}


def as_mapping(value: object) -> Mapping[str, Any]:
    """Convert a native result object, model, or JSON string to a mapping."""
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise DetectorParseError("Detector output is not valid JSON") from exc
        if isinstance(decoded, Mapping):
            return decoded
    if hasattr(value, "to_dict"):
        converted = value.to_dict()
        if isinstance(converted, Mapping):
            return converted
    if hasattr(value, "model_dump"):
        converted = value.model_dump()
        if isinstance(converted, Mapping):
            return converted
    if hasattr(value, "__dict__"):
        converted = vars(value)
        if isinstance(converted, Mapping):
            return converted
    raise DetectorParseError(f"Detector payload must be an object, got {type(value).__name__}")


def field(value: object, name: str) -> object | None:
    """Read a field from either a native object or a mapping."""
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def required_string(value: object, field_name: str) -> str:
    """Require a non-empty native string."""
    if not isinstance(value, str) or not value.strip():
        raise DetectorParseError(f"{field_name} must be a non-empty string")
    return value


def optional_string(value: object) -> str | None:
    """Return a non-empty string or ``None``."""
    return value if isinstance(value, str) and value else None


def mapping(value: object) -> dict[str, Any]:
    """Copy a mapping-valued native metadata field."""
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def offsets(data: Mapping[str, Any], index: int) -> tuple[int, int] | None:
    """Read optional tuple/list or start/end offsets."""
    value = data.get("offsets")
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) == 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError) as exc:
            raise DetectorParseError(f"record {index} offsets must contain integers") from exc
    if data.get("start") is None and data.get("end") is None:
        return None
    return required_offsets(data, index)


def required_offsets(data: object, index: int) -> tuple[int, int]:
    """Read required integer start/end fields."""
    start = field(data, "start")
    end = field(data, "end")
    try:
        return int(start), int(end)
    except (TypeError, ValueError) as exc:
        raise DetectorParseError(f"detector result {index} requires integer start/end") from exc


def valid_offsets(text: str, start: int, end: int) -> bool:
    """Return whether an offset pair is within the source text."""
    return 0 <= start < end <= len(text)


def confidence(value: object) -> float | None:
    """Convert an optional native score to a float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise DetectorParseError("confidence must be numeric") from exc


def confidentiality_judgment(value: object) -> ConfidentialityJudgment:
    """Read an explicit fresh confidentiality judgment, including its reason."""
    judgment = ConfidentialityJudgment.model_validate(value)
    if judgment.reason is None:
        raise DetectorParseError("confidentiality.reason is required for fresh detector output")
    return judgment


def necessity_judgment(value: object) -> NecessityJudgment:
    """Read an explicit fresh task-necessity judgment, including its reason."""
    judgment = NecessityJudgment.model_validate(value)
    if judgment.reason is None:
        raise DetectorParseError("necessity.reason is required for fresh detector output")
    return judgment


def normalize_kind(
    value: object,
    *,
    default: Literal["contextual", "structural"],
) -> Literal["contextual", "structural"]:
    """Validate a semantic kind and reject unknown explicit values."""
    if value is None:
        return default
    if value in {"contextual", "structural"}:
        return value
    raise DetectorParseError(f"kind must be 'contextual' or 'structural', got {value!r}")


def explanation(value: object) -> str | None:
    """Read a textual explanation from a native explanation object."""
    if isinstance(value, Mapping):
        for key in ("textual_explanation", "explanation", "text"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate
        return None
    for key in ("textual_explanation", "explanation", "text"):
        candidate = getattr(value, key, None)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return None


def presidio_method(metadata: Mapping[str, Any]) -> Literal["regex", "ner", "hybrid"]:
    """Infer the Presidio recognizer mechanism from its metadata."""
    name = str(metadata.get("recognizer_name", "")).lower()
    if "pattern" in name or "regex" in name or name.endswith("emailrecognizer"):
        return "regex"
    if any(token in name for token in ("spacy", "stanza", "ner", "transformer")):
        return "ner"
    return "hybrid"


def canonical_tag(native_label: str, span: str) -> str:
    """Map a native label to a safe reusable project tag."""
    if native_label in _LABEL_TO_TAG:
        return _LABEL_TO_TAG[native_label]
    lowered = native_label.lower()
    for label, tag in _LABEL_TO_TAG.items():
        if label.lower() == lowered:
            return tag
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", native_label).strip("_").upper()
    if not normalized:
        return "SENSITIVE"
    span_tokens = {token.upper() for token in re.findall(r"[A-Za-z0-9]+", span)}
    if set(normalized.split("_")) & span_tokens:
        return "SENSITIVE"
    return normalized
