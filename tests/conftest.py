import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def crux_current_fixture() -> dict:
    return json.loads((FIXTURES / "crux-current-wikipedia-phone.json").read_text())


@pytest.fixture
def lh13_fixture() -> dict:
    return json.loads((FIXTURES / "lh13-wikipedia-mobile.json").read_text())
