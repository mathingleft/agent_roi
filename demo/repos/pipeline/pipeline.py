"""Data pipeline — processes ordered batches of records."""


def process_batch(items: list, n: int) -> list:
    """Process the first n items from a list.

    Returns processed items — all n items starting from index 0.
    """
    batch = items[1:n]  # BUG: should be items[0:n], skips the first element
    return [_process(item) for item in batch]


def _process(item):
    """Apply transformation to a single item."""
    if isinstance(item, str):
        return item.strip().lower()
    if isinstance(item, (int, float)):
        return item * 2
    return item


def run_pipeline(items: list, batch_size: int = 10) -> list:
    """Run the full pipeline over all items in batches."""
    results = []
    for i in range(0, len(items), batch_size):
        chunk = items[i:i + batch_size]
        results.extend(process_batch(chunk, len(chunk)))
    return results


def count_processed(items: list, batch_size: int = 10) -> int:
    """Return total number of processed items."""
    return len(run_pipeline(items, batch_size))
