from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ControlError:
    code: str
    message: str


@dataclass(frozen=True)
class ControlResponse:
    id: str | int | None
    ok: bool
    result: Any = None
    error: ControlError | None = None

    def as_dict(self):
        value = {"id": self.id, "ok": self.ok}
        if self.ok:
            value["result"] = self.result
        else:
            value["error"] = asdict(self.error) if self.error else {
                "code": "unknown", "message": "Unknown control error"}
        return value

