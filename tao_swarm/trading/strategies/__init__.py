"""
Concrete trading strategies.

Each strategy is its own module. The package itself is empty of
imports so a strategy that depends on bittensor / numpy / etc.
doesn't pull those into the import graph for callers that don't
use it.

To register a strategy with the orchestrator, instantiate it and
hand it to whatever wires the runner. Auto-discovery (analogous to
the agent plug-in loader) is intentionally not part of PR 2D —
hand-wiring keeps the audit trail clean for the first concrete
strategy.
"""
