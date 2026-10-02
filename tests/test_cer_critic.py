import os
from unittest.mock import patch
from engine.cer_critic import generate_strategic_constraint

def test_critic_returns_string():
    """
    Test that the critic returns a valid string constraint.
    We mock the OPENROUTER_API_KEY to ensure we test the fallback path
    and avoid flaky network calls to free-tier external APIs during CI/pytest.
    """
    with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
        constraint = generate_strategic_constraint(
            "def foo(): return 1/0", 
            "ZeroDivisionError", 
            "Fix the division"
        )
        
        # Verify it returns the expected fallback string
        assert isinstance(constraint, str)
        assert len(constraint) > 0
        assert "CRITICAL STRATEGY SHIFT" in constraint
