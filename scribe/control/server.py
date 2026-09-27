"""Decoding one control request and encoding its response."""
from __future__ import annotations

import json
import logging

from .errors import ControlFailure
from .models import ControlError, ControlResponse

MAX_REQUEST_BYTES = 2 * 1024 * 1024
log = logging.getLogger("scribe.control")


def _reject_constant(_):
    raise ValueError("Non-finite JSON numbers are not supported")


def handle_line(service, line: str) -> dict:
    request_id = None
    try:
        if len(line.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ControlFailure("invalid_request", "Request exceeds the 2 MiB size limit")
        request = json.loads(line, parse_constant=_reject_constant)
        if not isinstance(request, dict):
            raise ControlFailure("invalid_request", "Request must be an object")
        candidate = request.get("id")
        if (candidate is not None and type(candidate) not in (str, int)
                or isinstance(candidate, str) and len(candidate) > 128):
            raise ControlFailure("invalid_request", "Request id must be a short string, integer or null")
        request_id = candidate
        if set(request) - {"id", "method", "params"} or not isinstance(request.get("method"), str):
            raise ControlFailure("invalid_request", "Request fields are invalid")
        result = service.dispatch(request["method"], request.get("params"))
        return ControlResponse(request_id, True, result=result).as_dict()
    except (ValueError, UnicodeError, RecursionError):
        return ControlResponse(request_id, False, error=ControlError("invalid_json", "Request is not valid JSON")).as_dict()
    except ControlFailure as exc:
        return ControlResponse(request_id, False, error=ControlError(exc.code, str(exc))).as_dict()
    except Exception:
        log.exception("control request failed")
        return ControlResponse(request_id, False, error=ControlError("internal_error", "Control operation failed")).as_dict()
