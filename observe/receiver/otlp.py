from collections.abc import Iterator
from typing import Any

from observe.sink.sink import ErrorEvent


def otlp_to_errors(data: dict[str, Any]) -> Iterator[ErrorEvent]:
    """Walk an OTLP JSON payload, yielding an ErrorEvent per span and log record."""
    for rs in data.get("resourceSpans", []):
        for ss in rs.get("scopeSpans", []):
            for sp in ss.get("spans", []):
                yield span_to_error(sp)
    for rl in data.get("resourceLogs", []):
        for sl in rl.get("scopeLogs", []):
            for log in sl.get("logRecords", []):
                yield log_to_error(log)


def span_to_error(sp: dict[str, Any]) -> ErrorEvent:
    attrs = _extract_attrs(sp.get("attributes", []))
    return ErrorEvent(
        message=sp.get("name", "otel span"),
        level=attrs.pop("level", "error"),
        timestamp=str(sp.get("startTimeUnixNano", "")),
        context=attrs,
        trace_id=sp.get("traceId"),
        span_id=sp.get("spanId"),
    )


def log_to_error(log: dict[str, Any]) -> ErrorEvent:
    attrs = _extract_attrs(log.get("attributes", []))
    body = log.get("body", {})
    raw = body.get("stringValue") or body.get("jsonValue") if isinstance(body, dict) else body
    message = str(raw) if raw else "otel log"
    return ErrorEvent(
        message=message,
        level=attrs.pop("severity", "error"),
        timestamp=str(log.get("timeUnixNano", "")),
        context=attrs,
    )


def _extract_attrs(items: list[Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for attr in items:
        key = attr.get("key", "")
        val = attr.get("value", {})
        if "stringValue" in val:
            result[key] = val["stringValue"]
        elif "intValue" in val:
            result[key] = int(val["intValue"])
        elif "doubleValue" in val:
            result[key] = val["doubleValue"]
        elif "boolValue" in val:
            result[key] = val["boolValue"]
    return result
