---
to: tests/test_<%= h.snake(name) %>_score.py
---
"""Tests for <%= h.pascal(name) %>Scorer."""

from src.scoring.<%= h.snake(name) %>_score import (
    <%= h.pascal(name) %>Scorer,
    SCORER_NAME,
)


def test_scorer_metadata():
    assert SCORER_NAME == "<%= h.snake(name) %>_score"


def test_scorer_with_no_weights_returns_zero():
    scorer = <%= h.pascal(name) %>Scorer(weights={})
    out = scorer.score({})
    assert out["score"] == 0.0


def test_scorer_clamps_to_range():
    scorer = <%= h.pascal(name) %>Scorer(weights={"x": 1.0})
    high = scorer.score({"x": 9999})
    low = scorer.score({"x": -9999})
    assert high["score"] == 100.0
    assert low["score"] == 0.0
