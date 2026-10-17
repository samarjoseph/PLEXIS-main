"""
Transform fast-path parser tests — pytest-compatible.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from router.master_router import _parse_transform_from_message, _TRANSFORM_RX


def _check(message, expected_type, expected_fields=None):
    result = _parse_transform_from_message(message)
    if expected_type is None:
        assert result is None, f"Expected None for {message!r}, got {result}"
        return
    assert result is not None, f"Parser returned None for {message!r}"
    assert result.get('type') == expected_type, \
        f"Expected type={expected_type}, got type={result.get('type')} for {message!r}"
    if expected_fields:
        for k, v in expected_fields.items():
            assert result.get(k) == v, \
                f"Expected {k}={v!r}, got {k}={result.get(k)!r} for {message!r}"


# FILL_MISSING
def test_fill_the_missing_values():
    _check("fill the missing values with 0", "FILL_MISSING", {"value": 0})

def test_fill_missing_42():
    _check("fill missing values with 42", "FILL_MISSING", {"value": 42})

def test_fill_null_with_0():
    _check("fill null values with 0", "FILL_MISSING", {"value": 0})

def test_replace_all_missing_values():
    _check("replace all missing values with 0", "FILL_MISSING", {"value": 0})

def test_fill_empty_values():
    _check("fill empty values with unknown", "FILL_MISSING", {"value": "unknown"})


# DROP_COLUMN
def test_drop_column_email():
    _check("drop column email", "DROP_COLUMN", {"column": "email"})

def test_remove_column_phone():
    _check("remove the column phone", "DROP_COLUMN", {"column": "phone"})

def test_delete_col_name():
    _check("delete the col name", "DROP_COLUMN", {"column": "name"})


# RENAME_COLUMN
def test_rename_age_to_user_age():
    _check("rename age to user_age", "RENAME_COLUMN", {"column": "age", "new_name": "user_age"})

def test_rename_column_city():
    _check("rename column city to location", "RENAME_COLUMN", {"column": "city", "new_name": "location"})


# DROP_DUPLICATES
def test_drop_duplicates():
    _check("drop duplicates", "DROP_DUPLICATES")

def test_remove_duplicate_rows():
    _check("remove duplicate rows", "DROP_DUPLICATES")

def test_deduplicate():
    _check("deduplicate", "DROP_DUPLICATES")


# SORT_ROWS
def test_sort_by_age():
    _check("sort by age", "SORT_ROWS", {"column": "age"})

def test_sort_by_age_desc():
    _check("sort by age descending", "SORT_ROWS", {"column": "age", "ascending": False})

def test_order_by_salary():
    _check("order by salary", "SORT_ROWS", {"column": "salary"})


# FILTER_ROWS
def test_filter_age_gt_30():
    _check("filter rows where age > 30", "FILTER_ROWS", {"column": "age", "operator": ">", "value": 30})

def test_keep_salary_gte():
    _check("keep rows where salary >= 50000", "FILTER_ROWS", {"column": "salary", "operator": ">=", "value": 50000})


# CAST_DTYPE
def test_convert_age_to_int():
    _check("convert age to integer", "CAST_DTYPE", {"column": "age", "dtype": "int"})

def test_cast_salary_to_float():
    _check("cast salary to float", "CAST_DTYPE", {"column": "salary", "dtype": "float"})


# REPLACE_VALUES — type-aware
def test_replace_delhi_with_mumbai_are_strings():
    result = _parse_transform_from_message("replace Delhi with Mumbai")
    assert result is not None
    assert result["type"] == "REPLACE_VALUES"
    assert result["old_value"] == "Delhi"
    assert isinstance(result["old_value"], str)

def test_replace_int_0_with_unknown():
    result = _parse_transform_from_message("replace 0 with unknown")
    assert result is not None
    assert result["type"] == "REPLACE_VALUES"
    assert result["old_value"] == 0
    assert isinstance(result["old_value"], int)

def test_replace_quoted_0_with_unknown():
    result = _parse_transform_from_message("replace '0' with unknown")
    assert result is not None
    assert result["type"] == "REPLACE_VALUES"
    assert result["old_value"] == "0"
    assert isinstance(result["old_value"], str)


# Should NOT match
def test_no_match_question():
    _check("What is the average age?", None)

def test_no_match_hello():
    _check("hello", None)


if __name__ == '__main__':
    import subprocess
    subprocess.run([sys.executable, '-m', 'pytest', __file__, '-v'])
