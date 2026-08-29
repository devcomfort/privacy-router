from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .parser import ParsedEntity
from .schemas import Requiredness


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


class LLMParser:
    """Parse structured output produced by the LiteLLM-backed extractor."""

    def parse(self, raw: object, text: str) -> list[ParsedEntity]:
        payload = _as_mapping(raw)
        records = payload.get("records", payload.get("entities", []))
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
            raise DetectorParseError("LLM output records must be an array")

        parsed: list[ParsedEntity] = []
        for index, item in enumerate(records):
            data = _as_mapping(item)
            tag = _required_string(data.get("tag") or data.get("category"), f"LLM record {index} tag")
            span = _required_string(data.get("span"), f"LLM record {index} span")
            parsed.append(
                ParsedEntity(
                    tag=_canonical_tag(tag, span),
                    kind=_kind(data.get("kind"), default="contextual"),
                    native_label=_optional_string(data.get("native_label")) or tag,
                    span=span,
                    offsets=_offsets(data, index),
                    reason=_optional_string(data.get("reason") or data.get("reasoning")),
                    confidence=_confidence(data.get("confidence")),
                    detection_method="llm",
                    native_metadata=_mapping(data.get("native_metadata")),
                    is_required=_requiredness(data.get("is_required")),
                )
            )
        return parsed


class PresidioParser:
    """Parse Presidio ``RecognizerResult`` objects or equivalent dictionaries."""

    def parse(self, raw: object, text: str) -> list[ParsedEntity]:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise DetectorParseError("Presidio output must be a result array")

        parsed: list[ParsedEntity] = []
        for index, item in enumerate(raw):
            entity_type = _required_string(_field(item, "entity_type"), f"Presidio result {index} entity_type")
            start, end = _required_offsets(item, index)
            if not _valid_offsets(text, start, end):
                raise DetectorParseError(f"Presidio result {index} has invalid offsets: {(start, end)!r}")
            metadata = _mapping(_field(item, "recognition_metadata"))
            explanation = _field(item, "analysis_explanation")
            parsed.append(
                ParsedEntity(
                    tag=_canonical_tag(entity_type, text[start:end]),
                    kind="structural",
                    native_label=entity_type,
                    span=text[start:end],
                    offsets=(start, end),
                    reason=_explanation(explanation),
                    confidence=_confidence(_field(item, "score")),
                    detection_method=_presidio_method(metadata),
                    native_metadata=metadata,
                    is_required=Requiredness(value=None, reason="not assessed"),
                )
            )
        return parsed


class OPFParser:
    """Parse typed OpenAI Privacy Filter output without applying redaction."""

    def parse(self, raw: object, text: str) -> list[ParsedEntity]:
        payload = _as_mapping(raw)
        spans = payload.get("detected_spans")
        if not isinstance(spans, Sequence) or isinstance(spans, (str, bytes)):
            raise DetectorParseError("OPF output detected_spans must be an array")

        parsed: list[ParsedEntity] = []
        for index, item in enumerate(spans):
            data = _as_mapping(item)
            label = _required_string(data.get("label"), f"OPF span {index} label")
            start, end = _required_offsets(data, index)
            if not _valid_offsets(text, start, end):
                raise DetectorParseError(f"OPF span {index} has invalid offsets: {(start, end)!r}")
            span = _optional_string(data.get("text")) or text[start:end]
            metadata = {key: value for key, value in data.items() if key not in {"label", "start", "end", "text"}}
            parsed.append(
                ParsedEntity(
                    tag=_canonical_tag(label, span),
                    kind="structural",
                    native_label=label,
                    span=span,
                    offsets=(start, end),
                    reason=None,
                    confidence=None,
                    detection_method="token_classifier",
                    native_metadata=metadata,
                    is_required=Requiredness(value=None, reason="not assessed"),
                )
            )
        return parsed


class LFMParser:
    """Parse decoded LFM2.5 PII spans."""

    def parse(self, raw: object, text: str) -> list[ParsedEntity]:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise DetectorParseError("LFM output must be a decoded span array")

        parsed: list[ParsedEntity] = []
        for index, item in enumerate(raw):
            data = _as_mapping(item)
            label = _required_string(
                data.get("label") or data.get("entity_type") or data.get("category") or data.get("type"),
                f"LFM span {index} label",
            )
            start, end = _required_offsets(data, index)
            if not _valid_offsets(text, start, end):
                raise DetectorParseError(f"LFM span {index} has invalid offsets: {(start, end)!r}")
            span = _optional_string(data.get("text") or data.get("span")) or text[start:end]
            metadata = {
                key: value
                for key, value in data.items()
                if key not in {"label", "entity_type", "category", "type", "start", "end", "text", "span", "score", "confidence"}
            }
            parsed.append(
                ParsedEntity(
                    tag=_canonical_tag(label, span),
                    kind="structural",
                    native_label=label,
                    span=span,
                    offsets=(start, end),
                    reason=None,
                    confidence=_confidence(data.get("confidence", data.get("score"))),
                    detection_method="token_classifier",
                    native_metadata=metadata,
                    is_required=Requiredness(value=None, reason="not assessed"),
                )
            )
        return parsed


def _as_mapping(value: object) -> Mapping[str, Any]:
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


def _field(value: object, name: str) -> object | None:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DetectorParseError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _offsets(data: Mapping[str, Any], index: int) -> tuple[int, int] | None:
    value = data.get("offsets")
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) == 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError) as exc:
            raise DetectorParseError(f"record {index} offsets must contain integers") from exc
    if data.get("start") is None and data.get("end") is None:
        return None
    return _required_offsets(data, index)


def _required_offsets(data: object, index: int) -> tuple[int, int]:
    start = _field(data, "start")
    end = _field(data, "end")
    try:
        return int(start), int(end)
    except (TypeError, ValueError) as exc:
        raise DetectorParseError(f"detector result {index} requires integer start/end") from exc


def _valid_offsets(text: str, start: int, end: int) -> bool:
    return 0 <= start < end <= len(text)


def _confidence(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise DetectorParseError("confidence must be numeric") from exc


def _requiredness(value: object) -> Requiredness:
    if isinstance(value, Requiredness):
        return value
    if isinstance(value, Mapping):
        return Requiredness.model_validate(value)
    return Requiredness(value=None, reason="not assessed")


def _kind(value: object, *, default: str) -> str:
    if value is None:
        return default
    if value in {"contextual", "structural"}:
        return value
    raise DetectorParseError(f"kind must be 'contextual' or 'structural', got {value!r}")


def _explanation(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key in ("textual_explanation", "explanation", "text"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
        return None
    for key in ("textual_explanation", "explanation", "text"):
        candidate = getattr(value, key, None)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _presidio_method(metadata: Mapping[str, Any]) -> str:
    name = str(metadata.get("recognizer_name", "")).lower()
    if "pattern" in name or "regex" in name or name.endswith("emailrecognizer"):
        return "regex"
    if any(token in name for token in ("spacy", "stanza", "ner", "transformer")):
        return "ner"
    return "hybrid"


def _canonical_tag(native_label: str, span: str) -> str:
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
