import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import publisher  # noqa: E402


class FakeResp:
    def __init__(self, status=200, body=None, text="Accepted"):
        self.status_code, self._body, self.text = status, body, text

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def test_make_route_used_and_confirmed(monkeypatch, tmp_path):
    img = tmp_path / "card.jpg"
    img.write_bytes(b"jpg")
    sent = {}
    monkeypatch.setattr(publisher, "MAKE_WEBHOOK_URL", "https://hook.make.test/abc")
    monkeypatch.setattr(publisher, "host_image", lambda p: "https://cdn.test/card.jpg")
    monkeypatch.setattr(publisher.requests, "post",
                        lambda url, json, timeout: sent.update(url=url, json=json) or FakeResp(body={"media_id": "123"}))
    out = publisher.publish(img, "caption", {"game_id": 7, "player_name": "X", "date": "2026-10-15"})
    assert out["media_id"] == "123"
    assert sent["json"]["image_url"] == "https://cdn.test/card.jpg" and sent["json"]["sample"] is False


def test_make_unconfirmed_is_a_failure(monkeypatch):
    """A bare 'Accepted' must not be recorded as posted."""
    monkeypatch.setattr(publisher, "MAKE_WEBHOOK_URL", "https://hook.make.test/abc")
    monkeypatch.setattr(publisher.requests, "post", lambda *a, **k: FakeResp())
    try:
        publisher.publish_via_make("u", "c")
    except publisher.PublishError:
        return
    raise AssertionError("expected PublishError")


def test_make_error_raises(monkeypatch):
    monkeypatch.setattr(publisher, "MAKE_WEBHOOK_URL", "https://hook.make.test/abc")
    monkeypatch.setattr(publisher.requests, "post", lambda *a, **k: FakeResp(status=500, text="boom"))
    try:
        publisher.publish_via_make("u", "c")
    except publisher.PublishError:
        return
    raise AssertionError("expected PublishError")
