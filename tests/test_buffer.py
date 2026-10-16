import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import buffer_client as bc  # noqa: E402


class Resp:
    def __init__(self, body, status=200):
        self._body, self.status_code, self.text = body, status, str(body)

    def json(self):
        return self._body


class FakeBuffer:
    """Answers the GraphQL calls buffer_client makes."""

    def __init__(self, statuses=("sending", "sent"), create_ok=True,
                 channels=({"id": "ch1", "name": "chirpanalytics", "displayName": "Chirp",
                            "service": "instagram", "isQueuePaused": False},)):
        self.statuses, self.create_ok, self.channels = list(statuses), create_ok, list(channels)
        self.created = None

    def __call__(self, url, json, timeout, headers):
        q = json["query"]
        assert headers["Authorization"] == "Bearer KEY"
        if "organizations" in q:
            return Resp({"data": {"account": {"organizations": [{"id": "org1", "name": "o"}]}}})
        if "channels(" in q:
            return Resp({"data": {"channels": self.channels}})
        if "createPost" in q:
            self.created = json["variables"]["input"]
            if not self.create_ok:
                return Resp({"data": {"createPost": {"__typename": "MutationError",
                                                     "message": "Image too large"}}})
            return Resp({"data": {"createPost": {"__typename": "PostActionSuccess",
                                                 "post": {"id": "p1", "status": "sending",
                                                          "externalLink": None}}}})
        if "post(input" in q:
            st = self.statuses.pop(0) if self.statuses else "sent"
            link = "https://www.instagram.com/p/abc/" if st == "sent" else None
            return Resp({"data": {"post": {"id": "p1", "status": st, "externalLink": link,
                                           "sentAt": None}}})
        raise AssertionError(q)


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(bc, "BUFFER_API_KEY", "KEY")
    monkeypatch.setattr(bc, "BUFFER_CHANNEL_ID", None)
    monkeypatch.setattr(bc, "_channel", None)
    monkeypatch.setattr(bc.time, "sleep", lambda s: None)


def test_carousel_published_and_confirmed(monkeypatch):
    fake = FakeBuffer()
    monkeypatch.setattr(bc.requests, "post", fake)
    out = bc.create_post(["u1", "u2", "u3"], "cap", alt_texts=["a", "b", "c"])
    assert out == {"media_id": "p1", "permalink": "https://www.instagram.com/p/abc/", "status": "sent"}
    inp = fake.created
    assert inp["mode"] == "shareNow" and inp["channelId"] == "ch1"
    assert [a["image"]["url"] for a in inp["assets"]] == ["u1", "u2", "u3"]
    assert inp["assets"][1]["image"]["metadata"]["altText"] == "b"


def test_refusal_raises(monkeypatch):
    monkeypatch.setattr(bc.requests, "post", FakeBuffer(create_ok=False))
    with pytest.raises(bc.BufferError, match="Image too large"):
        bc.create_post(["u1"], "cap")


def test_publish_error_status_raises(monkeypatch):
    monkeypatch.setattr(bc.requests, "post", FakeBuffer(statuses=["error"]))
    with pytest.raises(bc.BufferError, match="could not publish"):
        bc.create_post(["u1"], "cap")


def test_no_instagram_channel(monkeypatch):
    monkeypatch.setattr(bc.requests, "post", FakeBuffer(channels=[
        {"id": "x", "name": "page", "displayName": "", "service": "facebook", "isQueuePaused": False}]))
    with pytest.raises(bc.BufferError, match="No Instagram channel"):
        bc.create_post(["u1"], "cap")
