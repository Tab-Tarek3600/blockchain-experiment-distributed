from __future__ import annotations

import io

import requests

from src.ipfs.adapter import IPFSClient, IPFSError


class FakeResponse:
    def __init__(self, *, status_code=200, text="", content=b""):
        self.status_code = status_code
        self.text = text
        self.content = content

    @property
    def ok(self):
        return 200 <= self.status_code < 400


class FakeSession:
    def __init__(self):
        self.calls = []
        self.responses = []
        self.uploaded = None

    def post(self, url, **kwargs):
        files = kwargs.get("files")
        if files and "file" in files:
            self.uploaded = files["file"][1].read()
            files["file"][1].seek(0)
        self.calls.append((url, kwargs))
        return self.responses.pop(0)

    def close(self):
        pass


def test_add_returns_last_kubo_cid_and_sends_cid_v1():
    session = FakeSession()
    session.responses.append(
        FakeResponse(
            text='{"Name":"part","Hash":"QmOld","Size":"1"}\n'
            '{"Name":"part","Hash":"QmExpected","Size":"1"}\n'
        )
    )
    client = IPFSClient(session=session)

    cid = client.add_encrypted_file(b"ciphertext", filename="v1.bin")

    assert cid == "QmExpected"
    url, kwargs = session.calls[0]
    assert url.endswith("/add")
    assert kwargs["params"] == {"pin": "true", "cid-version": "1"}
    assert kwargs["files"]["file"][0] == "v1.bin"
    assert session.uploaded == b"ciphertext"


def test_get_pin_unpin_and_has():
    session = FakeSession()
    session.responses.extend(
        [
            FakeResponse(content=b"ciphertext"),
            FakeResponse(),
            FakeResponse(),
            FakeResponse(),
        ]
    )
    client = IPFSClient(session=session)

    assert client.get_file("QmTest") == b"ciphertext"
    client.pin("QmTest")
    client.unpin("QmTest")
    assert client.has("QmTest") is True

    assert [call[0].split("/api/v0/", 1)[1] for call in session.calls] == [
        "cat",
        "pin/add",
        "pin/rm",
        "block/stat",
    ]


def test_has_returns_false_for_missing_block():
    session = FakeSession()
    session.responses.append(FakeResponse(status_code=500, text="block not found"))
    client = IPFSClient(session=session)

    assert client.has("QmMissing") is False


def test_bad_add_response_raises():
    session = FakeSession()
    session.responses.append(FakeResponse(text='{"Name":"x"}'))
    client = IPFSClient(session=session)

    try:
        client.add_encrypted_file(io.BytesIO(b"ciphertext"))
    except IPFSError as exc:
        assert "CID" in str(exc)
    else:
        raise AssertionError("IPFSError attendu")


def test_transport_error_is_wrapped():
    class BrokenSession(FakeSession):
        def post(self, url, **kwargs):
            raise requests.ConnectionError("down")

    client = IPFSClient(session=BrokenSession())

    try:
        client.get_file("QmTest")
    except IPFSError as exc:
        assert "communication IPFS" in str(exc)
    else:
        raise AssertionError("IPFSError attendu")
