"""
Dashboard module for TAO/Bittensor Multi-Agent System.

Provides a Streamlit-based dashboard for visualizing system state,
subnet scores, wallet watch, market data, risk alerts, and run logs.
"""

from .app import main

__all__ = ["main"]
