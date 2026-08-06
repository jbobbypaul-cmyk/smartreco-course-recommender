import os
os.environ.setdefault("ENABLE_SCHEDULER", "false")
from app.main import app


def test_app_exists():
    assert app.title == "SmartReco"

