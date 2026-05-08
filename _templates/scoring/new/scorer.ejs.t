---
to: src/scoring/<%= h.snake(name) %>_score.py
---
"""
<%= h.pascal(name) %> scoring.

<%= description %>
"""

from __future__ import annotations

from typing import Any

SCORER_NAME: str = "<%= h.snake(name) %>_score"
SCORER_VERSION: str = "1.0.0"

# Adjust weights to sum to 1.0
CRITERIA_WEIGHTS: dict[str, float] = {
    # "criterion_a": 0.5,
    # "criterion_b": 0.5,
}


class <%= h.pascal(name) %>Scorer:
    """<%= description %>"""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights: dict[str, float] = dict(weights or CRITERIA_WEIGHTS)

    def score(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Compute a 0..100 score from the input payload."""
        if not self.weights:
            return {"score": 0.0, "components": {}, "reason": "no_weights_configured"}

        components: dict[str, float] = {}
        total = 0.0
        for key, weight in self.weights.items():
            value = float(payload.get(key, 0.0))
            components[key] = value
            total += value * weight

        return {
            "score": max(0.0, min(100.0, total)),
            "components": components,
            "weights": self.weights,
        }
