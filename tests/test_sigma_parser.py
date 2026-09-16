import pytest
from engine.sigma_parser import parse_sigma_rule, SigmaParserError

def test_valid_sigma_rule():
    """Test parsing a valid Sigma rule."""
    valid_rule = """
    id: 123e4567-e89b-12d3-a456-426614174000
    title: Suspicious Process Execution
    level: high
    description: Detects suspicious process execution patterns
    logsource:
        category: process_creation
        product: windows
    detection:
        selection:
            Image|endswith: '\\rundll32.exe'
        condition: selection
    """
    result = parse_sigma_rule(valid_rule)
    assert result.rule_id == "123e4567-e89b-12d3-a456-426614174000"
    assert result.title == "Suspicious Process Execution"
    assert result.severity == "high"

def test_missing_required_field():
    """Test that invalid data raises a parser error."""
    invalid_rule = """
    title: Missing Required Fields
    detection:
        selection:
            Image: 'cmd.exe'
    """
    with pytest.raises(SigmaParserError, match="Validation error"):
        parse_sigma_rule(invalid_rule)

def test_invalid_yaml():
    """Test parsing invalid YAML raises a parser error."""
    invalid_yaml = """
    title: Invalid YAML
    detection:
        selection:
            Image: 'cmd.exe'
        condition: selection
    foo: bar: baz
    """
    with pytest.raises(SigmaParserError, match="YAML parsing error"):
        parse_sigma_rule(invalid_yaml)
