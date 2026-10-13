import contextlib
from collections.abc import Iterator
from typing import Any

from observe.sink.sink import ErrorEvent


def otlp_to_errors(data: dict[str, Any]) -> Iterator[ErrorEvent]:
    """Walk an OTLP JSON payload, yielding an ErrorEvent per span and log record.

    The payload comes from the browser, so anything that is not the expected
    list of objects is skipped.
    """
    for rs in _dicts(data.get("resourceSpans")):
        for ss in _dicts(rs.get("scopeSpans")):
            for sp in _dicts(ss.get("spans")):
                yield span_to_error(sp)
    for rl in _dicts(data.get("resourceLogs")):
        for sl in _dicts(rl.get("scopeLogs")):
            for log in _dicts(sl.get("logRecords")):
                yield log_to_error(log)


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def span_to_error(sp: dict[str, Any]) -> ErrorEvent:
    attrs = _extract_attrs(sp.get("attributes"))
    return ErrorEvent(
        message=sp.get("name", "otel span"),
        level=attrs.pop("level", "error"),
        timestamp=str(sp.get("startTimeUnixNano", "")),
        context=attrs,
        trace_id=sp.get("traceId"),
        span_id=sp.get("spanId"),
    )


def log_to_error(log: dict[str, Any]) -> ErrorEvent:
    attrs = _extract_attrs(log.get("attributes"))
    body = log.get("body", {})
    raw = body.get("stringValue") or body.get("jsonValue") if isinstance(body, dict) else body
    message = str(raw) if raw else "otel log"
    return ErrorEvent(
        message=message,
        level=attrs.pop("severity", "error"),
        timestamp=str(log.get("timeUnixNano", "")),
        context=attrs,
    )


def _extract_attrs(items: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for attr in _dicts(items):
        key = attr.get("key", "")
        val = attr.get("value")
        if not isinstance(val, dict):
            continue
        if "stringValue" in val:
            result[key] = val["stringValue"]
        elif "intValue" in val:
            with contextlib.suppress(TypeError, ValueError):
                result[key] = int(val["intValue"])
        elif "doubleValue" in val:
            result[key] = val["doubleValue"]
        elif "boolValue" in val:
            result[key] = val["boolValue"]
    return result
