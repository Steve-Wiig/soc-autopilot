from engine.autopilot_stress_test import process_burst


def test_process_burst():
    """Test the process_burst function with a small number of alerts."""
    process_burst(10)
