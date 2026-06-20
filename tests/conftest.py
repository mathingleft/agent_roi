"""Pytest configuration shared across all test modules."""
from __future__ import annotations

import asyncio
import pytest


def run_async(coro):
    """Run a coroutine synchronously, creating a fresh event loop."""
    return asyncio.run(coro)
