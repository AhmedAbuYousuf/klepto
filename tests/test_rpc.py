import json

import httpx
import pytest

from klepto_dl.engine.aria2_rpc import Aria2RPC, DownloadSnapshot, EngineError, _unused_local_port


def test_snapshot_decodes_real_aria2_fields():
    snapshot = DownloadSnapshot.from_rpc({
        "gid": "0123456789abcdef", "status": "active", "completedLength": "1024",
        "totalLength": "2048", "downloadSpeed": "512", "dir": r"E:\Downloads",
        "files": [{"path": r"E:\Downloads\a.zip", "uris": [{"uri": "https://example.com/a.zip"}]}],
    })
    assert snapshot.completed == 1024
    assert snapshot.speed == 512
    assert snapshot.source_uri == "https://example.com/a.zip"
    assert snapshot.directory == r"E:\Downloads"


def test_rpc_sends_token_to_loopback_and_parses_methods():
    recorded = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append((str(request.url), json.loads(request.content)))
        payload = json.loads(request.content)
        meth = payload["method"]
        if meth == "aria2.addUri":
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": "abcd1234"})
        if meth == "aria2.tellStatus":
            return httpx.Response(200, json={"result": {"gid": "abcd1234", "status": "active", "completedLength": "8", "totalLength": "16", "downloadSpeed": "2"}})
        return httpx.Response(200, json={"result": "OK"})

    engine = Aria2RPC()
    engine._client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    engine._endpoint = "http://127.0.0.1:6001/jsonrpc"
    engine._token = "testing-secret"
    assert engine.add("https://example.org/a.zip", r"E:\Downloads") == "abcd1234"
    assert engine.tell_status("abcd1234").completed == 8
    engine.control("abcd1234", "pause")
    engine.control("abcd1234", "resume")
    engine.control("abcd1234", "cancel")
    assert all(url.startswith("http://127.0.0.1:6001") for url, _ in recorded)
    assert all(item["params"][0] == "token:testing-secret" for _, item in recorded)
    assert recorded[0][1]["params"][1:] == [["https://example.org/a.zip"], {"dir": r"E:\Downloads"}]
    assert [item["method"] for _, item in recorded] == [
        "aria2.addUri", "aria2.tellStatus", "aria2.pause", "aria2.unpause", "aria2.remove",
    ]
    engine.stop()


def test_rpc_reports_engine_error():
    engine = Aria2RPC()
    engine._client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"error": {"code": 1, "message": "Unauthorized"}})
    ))
    engine._endpoint = "http://127.0.0.1:6001/jsonrpc"
    engine._token = "bad-token"
    with pytest.raises(EngineError, match="Unauthorized"):
        engine.call("getVersion")
    engine.stop()


def test_invalid_control():
    with pytest.raises(EngineError, match="Unsupported"):
        Aria2RPC().control("abc", "execute")


def test_rpc_port_in_range():
    assert 1024 <= _unused_local_port() <= 65535
