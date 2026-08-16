from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    name: Optional[str]
    is_active: bool