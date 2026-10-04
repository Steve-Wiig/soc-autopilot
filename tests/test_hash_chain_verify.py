import pytest
from tools.hash_chain_verify import compute_row_hash, validate_entry_schema

def test_compute_row_hash_excludes_hash_field():
    row = {"chain_seq": 1, "previous_hash": "0"*64, "data": "test", "hash": "ignored"}
    row_no_hash = {"chain_seq": 1, "previous_hash": "0"*64, "data": "test"}
    assert compute_row_hash(row) == compute_row_hash(row_no_hash)

def test_validate_entry_schema_rejects_bad_seq():
    with pytest.raises(ValueError):
        validate_entry_schema({"chain_seq": "not_an_int", "previous_hash": "0"*64})

def test_placeholder():
    assert True
