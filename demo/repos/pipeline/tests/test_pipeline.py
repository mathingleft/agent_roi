import pytest
from pipeline import process_batch, run_pipeline, count_processed


def test_process_batch_includes_first_element():
    items = ["  Hello  ", "world", "foo"]
    result = process_batch(items, 3)
    assert result[0] == "hello", f"Expected 'hello', got '{result[0]}'"


def test_process_batch_correct_length():
    items = [1, 2, 3, 4, 5]
    result = process_batch(items, 3)
    assert len(result) == 3, f"Expected 3 items, got {len(result)}"


def test_process_batch_numbers_doubled():
    items = [10, 20, 30]
    result = process_batch(items, 3)
    assert result == [20, 40, 60]


def test_run_pipeline_all_items():
    items = list(range(5))  # [0, 1, 2, 3, 4]
    result = run_pipeline(items, batch_size=5)
    assert len(result) == 5, f"Expected 5 processed items, got {len(result)}"


def test_run_pipeline_values():
    items = [1, 2, 3]
    result = run_pipeline(items, batch_size=3)
    assert result == [2, 4, 6]


def test_count_processed():
    items = list(range(10))
    count = count_processed(items, batch_size=10)
    assert count == 10, f"Expected 10, got {count}"
