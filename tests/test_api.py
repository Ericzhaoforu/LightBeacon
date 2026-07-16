from fastapi.testclient import TestClient

from lightbeacon.app import create_app
from lightbeacon.config import Settings


def test_auth_layout_and_effect_validation(tmp_path) -> None:
    settings = Settings.for_test(tmp_path, udp_port=0)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/nodes").status_code == 401
        assert client.post("/api/v1/auth/login", json={"password": "wrong"}).status_code == 401
        assert client.post(
            "/api/v1/auth/login", json={"password": "test-password"}
        ).status_code == 200
        assert client.get("/api/v1/nodes").json() == []
        layout = {
            "rows": 2,
            "columns": 2,
            "cells": [{"row": 0, "column": 0, "node_id": "LB-001"}],
        }
        assert client.put("/api/v1/layout", json=layout).json() == layout
        assert client.get("/api/v1/layout").json() == layout
        invalid = {
            "node_ids": ["LB-001"],
            "mode": "BLINK_BLUE",
            "period_ms": 100,
            "brightness": 25,
        }
        assert client.post("/api/v1/effects", json=invalid).status_code == 422
        assert client.post("/api/v1/all-off").status_code == 200

