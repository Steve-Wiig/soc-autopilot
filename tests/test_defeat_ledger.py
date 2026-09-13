# HARDENED: 2026-09-13T05:47:53.016137+00:00
import pytest
import shutil
from pathlib import Path
from engine.defeat_ledger import (
    hash_ast, normalize_traceback, check_and_record_defeat, is_ast_defeated,
    LEDGER_PATH, DEFEAT_THRESHOLD
)

@pytest.fixture(autouse=True)
def clean_led():
    """Ensure every test starts with a blank ledger."""
    if LEDGER_PATH.exists():
        LEDGER_PATH.unlink()
    yield
    if LEDGER_PATH.exists():
        LEDGER_PATH.unlink()

def test_ast_hash_ignores_whitespace_and_comments():
    """Formatting changes must NOT change the AST hash."""
    code1 = "def foo():\n    # comment\n    return 1"
    code2 = "def foo():\n\n\n    return 1      "
    code3 = "def foo():\n    '''docstring'''\n    return 1"
    
    h1 = hash_ast(code1)
    assert h1 == hash_ast(code2), "Whitespace shift altered AST hash!"
    assert h1 == hash_ast(code3), "Docstring addition altered AST hash!"

def test_ast_hash_catches_logic_changes():
    """Actual logic changes MUST change the AST hash."""
    code1 = "def foo(): return 1"
    code2 = "def foo(): return 2"
    assert hash_ast(code1) != hash_ast(code2)

def test_traceback_normalization():
    """Line numbers and absolute paths must be stripped."""
    tb = "File 'str(Path(__file__).parent.parent.resolve())/engine/foo.py', line 42, in test_bar\n  AssertionError"
    norm = normalize_traceback(tb)
    assert "42" not in norm
    assert "/home/swiig" not in norm
    assert "<PATH>" in norm
    assert "line <N>" in norm

def test_defeat_threshold_triggers_quarantine():
    """3 strikes on the exact same logical failure must trigger DEFEATED."""
    code = "def broken(): return 1 / 0"
    tb = "ZeroDivisionError: division by zero at line 10"
    
    assert check_and_record_defeat("foo.py", code, tb) is False # Strike 1
    assert check_and_record_defeat("foo.py", code, tb) is False # Strike 2
    assert check_and_record_defeat("foo.py", code, tb) is True  # Strike 3 -> DEFEATED!

def test_formatting_shift_does_not_reset_strikes():
    """If the LLM adds a comment or shifts lines, the failure must still count towards defeat."""
    code_base = "def broken(): return 1 / 0"
    code_with_comment = "# LLM added a comment\ndef broken(): return 1 / 0"
    tb1 = "Error at /path/to/foo.py line 10"
    tb2 = "Error at /path/to/foo.py line 12" # Line shifted due to comment
    
    check_and_record_defeat("foo.py", code_base, tb1) # Strike 1
    check_and_record_defeat("foo.py", code_with_comment, tb2) # Strike 2 (AST and TB normalized!)
    
    # Strike 3 should trigger defeat
    assert check_and_record_defeat("foo.py", code_base, tb1) is True 

def test_is_ast_defeated_quarantines_file():
    """If an AST hash is marked defeated, is_ast_defeated must return True."""
    code = "def broken(): return 1 / 0"
    tb = "ZeroDivisionError"
    
    assert is_ast_defeated(code) is False # Not defeated yet
    
    check_and_record_defeat("foo.py", code, tb) # Strike 1
    check_and_record_defeat("foo.py", code, tb) # Strike 2
    check_and_record_defeat("foo.py", code, tb) # Strike 3
    
    assert is_ast_defeated(code) is True # QUARANTINED!
