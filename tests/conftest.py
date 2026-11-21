"""Shared fixtures. Loaded once per test session; no LLM or network calls anywhere in tests."""

from __future__ import annotations

import os
from datetime import date

import pytest

# Tests always run with the date the expected results assume, and with no pricing overrides,
# whatever is in the developer's .env.
os.environ["TODAY"] = "2026-11-19"
os.environ["PRICING_OVERRIDES_FILE"] = ""

from mira.data import load_content, load_decisions, load_workbook  # noqa: E402

TODAY = date(2026, 11, 19)


@pytest.fixture(scope="session")
def workbook():
    return load_workbook(today=TODAY)


@pytest.fixture(scope="session")
def content():
    return load_content()


@pytest.fixture(scope="session")
def decisions():
    return load_decisions()
