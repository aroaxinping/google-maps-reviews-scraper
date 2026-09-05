import json
import pytest
from pathlib import Path

JSONL_PATH = Path("/home/aroa/taal_vista_raw_batches.jsonl")


@pytest.fixture
def raw_batch_0():
    line = JSONL_PATH.read_text().splitlines()[0]
    return json.loads(line)


@pytest.fixture
def raw_batch_5():
    lines = JSONL_PATH.read_text().splitlines()
    return json.loads(lines[5])


@pytest.fixture
def tmp_db(tmp_path):
    from gmaps_reviews.storage import Store
    s = Store(tmp_path / "test.db")
    yield s
    s.close()
