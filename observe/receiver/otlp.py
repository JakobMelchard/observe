from observe.sink.sink import ErrorEvent


def span_to_error(sp: dict) -> ErrorEvent:
    attrs = _extract_attrs(sp.get("attributes", []))
    return ErrorEvent(
        message=sp.get("name", "otel span"),
        level=attrs.pop("level", "error"),
        timestamp=str(sp.get("startTimeUnixNano", "")),
        context=attrs,
        trace_id=sp.get("traceId"),
        span_id=sp.get("spanId"),
    )


def log_to_error(log: dict) -> ErrorEvent:
    attrs = _extract_attrs(log.get("attributes", []))
    body = log.get("body", {})
    message = (
        body.get("stringValue", body.get("jsonValue", "otel log"))
        if isinstance(body, dict)
        else str(body)
    )
    return ErrorEvent(
        message=message,
        level=attrs.pop("severity", "error"),
        timestamp=str(log.get("timeUnixNano", "")),
        context=attrs,
    )


def _extract_attrs(items: list) -> dict:
    result = {}
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
