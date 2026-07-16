"""Fail-closed adapter execution for already-selected privacy routes.

This module never chooses a model, re-runs privacy analysis, or prepares a
payload. It only retries the supplied invocation against the selected route.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Generator, Iterable
from dataclasses import dataclass
from typing import Literal, cast

import litellm

from .schemas import RouteResult

RouteName = Literal["local_api", "external_api", "unresolved"]
FailureReason = Literal[
    "timeout",
    "connection",
    "service_unavailable",
    "adapter_error",
    "extraction_failed",
    "route_invariant_failed",
    "masking_failed",
    "hydration_failed",
]

MAX_ATTEMPTS = 3
_RETRY_DELAYS = (1.0, 2.0)
_ROUTABLE_ENDPOINTS = frozenset({"local_api", "external_api"})
_TRANSPORT_REASONS = frozenset({"timeout", "connection", "service_unavailable"})
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PrivacyRouteFailure(Exception):
    """Safe description of a failed privacy-preserving route."""

    route: RouteName
    reason: FailureReason
    retryable: bool
    attempts: int
    status_code: int


def public_error_fields(failure: PrivacyRouteFailure, request_id: str) -> dict[str, object]:
    """Return the safe, client-facing fields for a route failure."""
    messages = {
        "timeout": "선택된 개인정보 보호 처리 경로가 일시적으로 응답하지 않았습니다. 요청은 다른 처리 경로로 전환되지 않았습니다.",
        "connection": "선택된 개인정보 보호 처리 경로와 연결할 수 없습니다. 요청은 다른 처리 경로로 전환되지 않았습니다.",
        "service_unavailable": "선택된 개인정보 보호 처리 경로를 일시적으로 사용할 수 없습니다. 요청은 다른 처리 경로로 전환되지 않았습니다.",
        "adapter_error": "선택된 개인정보 보호 처리 경로가 요청을 처리하지 못했습니다. 요청은 다른 처리 경로로 전환되지 않았습니다.",
        "extraction_failed": "개인정보 보호 분석을 안전하게 완료하지 못했습니다. 요청은 처리 경로로 전송되지 않았습니다.",
        "route_invariant_failed": "개인정보 보호 경로를 안전하게 확정하지 못했습니다. 요청은 처리 경로로 전송되지 않았습니다.",
        "masking_failed": "민감 정보를 안전하게 마스킹하지 못했습니다. 요청은 외부 처리 경로로 전송되지 않았습니다.",
        "hydration_failed": "응답을 안전하게 복원하지 못했습니다. 부분 응답은 반환되지 않았습니다.",
    }
    if failure.retryable and failure.attempts == MAX_ATTEMPTS:
        messages["timeout"] = (
            "선택된 개인정보 보호 처리 경로가 3회 시도 후 응답하지 않았습니다. "
            "요청은 다른 처리 경로로 전환되지 않았습니다."
        )
    codes = {
        "adapter_error": "privacy_route_unavailable",
        "timeout": "privacy_route_unavailable",
        "connection": "privacy_route_unavailable",
        "service_unavailable": "privacy_route_unavailable",
        "extraction_failed": "privacy_analysis_failed",
        "route_invariant_failed": "privacy_route_rejected",
        "masking_failed": "privacy_contract_failed",
        "hydration_failed": "privacy_contract_failed",
    }
    return {
        "code": codes[failure.reason],
        "reason": failure.reason,
        "message": messages[failure.reason],
        "retryable": failure.retryable,
        "attempts": failure.attempts,
        "request_id": request_id,
    }


def privacy_failure(
    reason: Literal[
        "extraction_failed",
        "route_invariant_failed",
        "masking_failed",
        "hydration_failed",
    ],
    *,
    route: RouteName = "unresolved",
) -> PrivacyRouteFailure:
    """Construct a non-retryable failure before or after adapter execution."""
    statuses = {
        "extraction_failed": 503,
        "route_invariant_failed": 409,
        "masking_failed": 502,
        "hydration_failed": 502,
    }
    return PrivacyRouteFailure(route, reason, False, 1, statuses[reason])


def log_privacy_failure(failure: PrivacyRouteFailure, request_id: str) -> None:
    """Log only safe failure metadata; never attach the caught exception."""
    _LOGGER.error(
        "privacy_route_failed",
        extra={
            "request_id": request_id,
            "route": failure.route,
            "attempts": failure.attempts,
            "reason": failure.reason,
            "retryable": failure.retryable,
        },
    )


def _reason_for(error: BaseException) -> FailureReason:
    if isinstance(error, (TimeoutError, litellm.Timeout, litellm.CompletionTimeout)):
        return "timeout"
    if isinstance(error, (ConnectionError, litellm.APIConnectionError)):
        return "connection"
    if isinstance(error, litellm.ServiceUnavailableError):
        return "service_unavailable"
    return "adapter_error"


def _validate_route(route: RouteResult, request_id: str) -> Literal["local_api", "external_api"]:
    if route.endpoint not in _ROUTABLE_ENDPOINTS:
        failure = privacy_failure("route_invariant_failed")
        log_privacy_failure(failure, request_id)
        raise failure
    return cast(Literal["local_api", "external_api"], route.endpoint)


def _handle_adapter_error(
    route: Literal["local_api", "external_api"],
    error: BaseException,
    attempt: int,
    request_id: str,
    sleep: Callable[[float], None],
    *,
    may_retry: bool,
) -> None:
    reason = _reason_for(error)
    is_transport_failure = reason in _TRANSPORT_REASONS
    if is_transport_failure and may_retry and attempt < MAX_ATTEMPTS:
        _LOGGER.warning(
            "privacy_route_retry",
            extra={
                "request_id": request_id,
                "route": route,
                "attempt": attempt + 1,
                "max_attempts": MAX_ATTEMPTS,
                "reason": reason,
            },
        )
        sleep(_RETRY_DELAYS[attempt - 1])
        return

    failure = PrivacyRouteFailure(
        route=route,
        reason=reason,
        retryable=is_transport_failure and may_retry,
        attempts=attempt,
        status_code=503 if is_transport_failure else 502,
    )
    log_privacy_failure(failure, request_id)
    raise failure from None


def execute_fixed_route[T](
    route: RouteResult,
    invoke: Callable[[], T],
    *,
    request_id: str,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Invoke one selected endpoint up to ``MAX_ATTEMPTS`` times."""
    endpoint = _validate_route(route, request_id)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return invoke()
        except PrivacyRouteFailure:
            raise
        except Exception as error:
            _handle_adapter_error(endpoint, error, attempt, request_id, sleep, may_retry=True)
    raise AssertionError("retry loop must return or raise")


def execute_fixed_stream[T](
    route: RouteResult,
    open_stream: Callable[[], Iterable[T]],
    *,
    request_id: str,
    sleep: Callable[[float], None] = time.sleep,
) -> Generator[T]:
    """Open a selected stream with retries only before its first item."""
    endpoint = _validate_route(route, request_id)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            iterator = iter(open_stream())
            first = next(iterator)
        except StopIteration:
            return
        except PrivacyRouteFailure:
            raise
        except Exception as error:
            _handle_adapter_error(endpoint, error, attempt, request_id, sleep, may_retry=True)
            continue

        yield first
        try:
            yield from iterator
            return
        except PrivacyRouteFailure:
            raise
        except Exception as error:
            _handle_adapter_error(endpoint, error, attempt, request_id, sleep, may_retry=False)
    raise AssertionError("stream retry loop must return or raise")
