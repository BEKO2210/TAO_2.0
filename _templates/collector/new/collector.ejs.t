---
to: src/collectors/<%= h.snake(name) %>.py
---
"""
<%= h.pascal(name) %> collector.

<%= description %>

READ-ONLY: collectors must never write to the chain or sign transactions.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

COLLECTOR_NAME: str = "<%= h.snake(name) %>"
COLLECTOR_VERSION: str = "1.0.0"


class <%= h.pascal(name) %>Collector:
    """<%= description %>"""

    def __init__(self, config: dict | None = None) -> None:
        self.config: dict = config or {}
        self._use_mock: bool = self.config.get("use_mock_data", True)

    def collect(self, **params: Any) -> dict[str, Any]:
        """Collect data and return a normalized payload."""
        # TODO: implement collection logic
        return {
            "collector": COLLECTOR_NAME,
            "version": COLLECTOR_VERSION,
            "params": params,
            "data": [],
        }
