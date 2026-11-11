"""Exercise the upload → mapping → training flow through the local HTTP boundary."""

import base64
from http.client import HTTPConnection
import json
import threading

import pytest

from bakery_forecast.webapp import PlaygroundState, WEB, create_server
from bakery_forecast.playground import read_upload


@pytest.fixture
def server():
    server = create_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def request(server, path, payload=None, headers=None):
    client = HTTPConnection(*server.server_address, timeout=60)
    options = {"Content-Type": "application/json"}
    options.update(headers or {})
    client.request(
        "POST" if payload is not None else "GET",
        path,
        json.dumps(payload) if payload is not None else None,
        options,
    )
    response = client.getresponse()
    status, kind, body = response.status, response.getheader("Content-Type"), response.read()
    client.close()
    return status, json.loads(body) if "application/json" in kind else body


def test_static_assets_and_upload_to_real_prediction(server):
    for path in ("/", "/app.js", "/style.css", "/template.csv", "/demo.csv"):
        status, body = request(server, path)
        assert status == 200 and body
    content = base64.b64encode((WEB / "demo.csv").read_bytes()).decode()
    status, uploaded = request(
        server, "/api/inspect", {"filename": "my_sales.csv", "content": content}
    )
    assert status == 200 and uploaded["rows"] == 360
    status, prepared = request(
        server, "/api/prepare", {"id": uploaded["id"], "columns": uploaded["suggested"]}
    )
    assert status == 200 and prepared["audit"]["products"] == 3
    status, result = request(
        server, "/api/train", {"id": uploaded["id"], "products": ["Багет"], "missing": "unknown"}
    )
    assert status == 200 and result["target_date"] == "2026-09-29"
    assert result["demo"] is False


def test_bad_input_and_cross_origin_requests(server):
    assert request(server, "/api/demo", {}, {"Origin": "https://unrelated.example"})[0] == 403
    assert request(server, "/", headers={"Host": "unrelated.example"})[0] == 403
    assert request(server, "/api/inspect", {"filename": "file.csv", "content": "!bad!"})[0] == 400
    assert request(server, "/api/train", {"id": "missing", "products": ["Багет"]})[0] == 400
    assert request(server, "/../pyproject.toml")[0] == 404
    status, demo = request(server, "/api/demo", {})
    assert status == 200 and demo["demo"] is True


def test_memory_session_limit_and_expiry():
    state = PlaygroundState()
    table = read_upload((WEB / "template.csv").read_bytes(), "template.csv")
    keys = [state.add(table, "sales.csv")["id"] for _ in range(5)]
    assert len(state.uploads) == 4
    with pytest.raises(ValueError, match="истёк"):
        state.get(keys[0])
    state.uploads[keys[-1]]["created"] -= 3601
    with pytest.raises(ValueError, match="истёк"):
        state.get(keys[-1])
    state.expire()
    assert keys[-1] not in state.uploads
