import pytest
from pydantic import ValidationError

from lightbeacon.database import Database
from lightbeacon.models import Layout


def test_layout_round_trip(tmp_path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    database.initialize()
    layout = Layout(
        rows=2,
        columns=3,
        cells=[{"row": 0, "column": 1, "node_id": "LB-001"}],
    )
    database.save_layout(layout)
    assert database.get_layout() == layout
    database.close()


def test_duplicate_node_binding_is_invalid() -> None:
    with pytest.raises(ValidationError):
        Layout(
            rows=2,
            columns=2,
            cells=[
                {"row": 0, "column": 0, "node_id": "LB-001"},
                {"row": 1, "column": 1, "node_id": "LB-001"},
            ],
        )

