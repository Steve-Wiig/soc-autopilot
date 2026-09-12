import pytest
import sys
import os

# Ensure project root is in path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from overnight.safety_gates import pre_flight_safety_check

def test_bare_except_rejection():
    bad_code = "try:\n    x = 1\nexcept Exception:\n    pass"
    is_safe, msg = pre_flight_safety_check(bad_code, "dummy.py")
    assert not is_safe
    assert "Bare 'except Exception:'" in msg

def test_hardcoded_path_rejection():
    bad_code = "path = '/home/swiig/data'"
    is_safe, msg = pre_flight_safety_check(bad_code, "dummy.py")
    assert not is_safe
    assert "Hardcoded absolute path" in msg

def test_contextmanager_enforcement():
    bad_code = "def read_file():\n    yield 'data'"
    is_safe, msg = pre_flight_safety_check(bad_code, "dummy.py")
    assert not is_safe
    assert "missing @contextmanager" in msg

def test_good_code_passes():
    good_code = "from contextlib import contextmanager\n@contextmanager\ndef read_file():\n    yield 'data'"
    is_safe, msg = pre_flight_safety_check(good_code, "dummy.py")
    assert is_safe
    assert "PASSED" in msg
