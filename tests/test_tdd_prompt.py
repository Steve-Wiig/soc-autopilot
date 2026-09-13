"""Tests for _build_tdd_prompt: route-specific prompt selection."""
import pytest

import overnight.self_improver as si


def test_local_tdd_prompt_asks_for_invariant():
    prompt = si._build_tdd_prompt(
        issue_desc="extract_json missing docstring",
        target_file="engine/consensus_gate.py",
        sig_context="",
        route="LOCAL_TDD",
    )
    assert "invariant" in prompt.lower()
    assert "inspect.getdoc" in prompt


def test_local_tdd_prompt_lists_structural_examples():
    prompt = si._build_tdd_prompt(
        issue_desc="extract a hardcoded string",
        target_file="engine/foo.py",
        sig_context="",
        route="LOCAL_TDD",
    )
    assert "docstring" in prompt.lower()
    assert "type annotation" in prompt.lower()


def test_review_prompt_uses_original_wording():
    prompt = si._build_tdd_prompt(
        issue_desc="integer overflow in parser",
        target_file="engine/parser.py",
        sig_context="",
        route="REVIEW",
    )
    assert "minimal failing pytest test" in prompt


def test_review_prompt_does_not_mention_invariant_workflow():
    prompt = si._build_tdd_prompt(
        issue_desc="integer overflow in parser",
        target_file="engine/parser.py",
        sig_context="",
        route="REVIEW",
    )
    assert "inspect.getdoc" not in prompt


def test_unknown_route_uses_default_prompt():
    prompt = si._build_tdd_prompt(
        issue_desc="something",
        target_file="engine/foo.py",
        sig_context="",
        route="UNKNOWN",
    )
    assert "minimal failing pytest test" in prompt


def test_local_tdd_prompt_includes_target_file():
    prompt = si._build_tdd_prompt(
        issue_desc="test",
        target_file="engine/consensus_gate.py",
        sig_context="REAL FUNCTION SIGNATURES:\ndef foo(x)\n",
        route="LOCAL_TDD",
    )
    assert "engine/consensus_gate.py" in prompt
    assert "def foo(x)" in prompt


def test_local_tdd_prompt_includes_import_rule():
    prompt = si._build_tdd_prompt(
        issue_desc="test",
        target_file="engine/foo.py",
        sig_context="",
        route="LOCAL_TDD",
    )
    assert "package-relative imports" in prompt
    assert "Do NOT import sys, os, subprocess, or shutil" in prompt


def test_generate_tdd_test_signature_accepts_route():
    import inspect
    sig = inspect.signature(si._generate_tdd_test)
    assert "route" in sig.parameters
    assert sig.parameters["route"].default == "REVIEW"


def test_build_tdd_prompt_is_pure():
    a = si._build_tdd_prompt("x", "y.py", "sig", "LOCAL_TDD")
    b = si._build_tdd_prompt("x", "y.py", "sig", "LOCAL_TDD")
    assert a == b
