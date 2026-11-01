from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """Raised by the service layer; converted to an HTTP error response in main.py."""

    def __init__(self, status_code: int, detail: Any):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


class NoDataError(ApiError):
    def __init__(self, material_id: str):
        super().__init__(404, f"No consumption data found for material '{material_id}'. Upload a CSV first.")
