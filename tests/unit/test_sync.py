"""IMAP sync, tested against an in-memory fake server (no network, no credentials)."""

import json
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest

from opspilot.schemas.enums import Profile
from opspilot.schemas.state import RawEmail
from opspilot.sync.imap_sync import MAX_MESSAGE_BYTES, SyncConfig, load_state, sync_once


def eml(subject: str, body: str = "hello", sender: str = "Anna <anna@firma.de>") -> bytes:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Date"] = (
        sender,
        "me@example.org",
        subject,
        "Mon, 16 Nov 2026 09:00:00 +0100",
    )
    m.set_content(body)
    return m.as_bytes()


class FakeImap:
    def __init__(
        self, messages: dict[int, bytes], validity: int = 7, sizes: dict[int, int] | None = None
    ) -> None:
        self.messages, self.validity, self.sizes = messages, validity, sizes or {}
        self.calls: list[tuple[str, ...]] = []
        self.selected: tuple[str, bool] | None = None
        self.logged_out = False

    def login(self, user: str, password: str) -> tuple[str, list[Any]]:
        self.calls.append(("login", user))
        return "OK", []

    def select(self, mailbox: str, readonly: bool) -> tuple[str, list[Any]]:
        self.selected = (mailbox, readonly)
        return "OK", [b"1"]

    def response(self, code: str) -> tuple[str, list[Any]]:
        return code, [str(self.validity).encode()]

    def uid(self, command: str, *args: str) -> tuple[str, list[Any]]:
        self.calls.append((command, *args))
        if command == "SEARCH":
            start = int(args[0].split(":")[0].split()[-1]) if args[0].startswith("UID") else 0
            hits = [u for u in self.messages if u >= start] or (
                [max(self.messages)] if args[0].startswith("UID") and self.messages else []
            )  # real servers return the last UID for 'N:*'
            return "OK", [" ".join(map(str, sorted(hits))).encode()]
        uid = int(args[0])
        if "RFC822.SIZE" in args[1]:
            return "OK", [
                f"{uid} (RFC822.SIZE {self.sizes.get(uid, len(self.messages[uid]))})".encode()
            ]
        return "OK", [(f"{uid} (BODY[] {{n}}".encode(), self.messages[uid]), b")"]

    def logout(self) -> tuple[str, list[Any]]:
        self.logged_out = True
        return "BYE", []


@pytest.fixture
def cfg(tmp_path: Path) -> SyncConfig:
    return SyncConfig(
        "imap.example",
        993,
        "me@example.org",
        "app-password",
        state_path=tmp_path / "state.json",
        max_per_run=10,
    )


def run(cfg: SyncConfig, server: FakeImap, ingest: Any = None) -> tuple[Any, list[RawEmail]]:
    seen: list[RawEmail] = []

    def default(raw: RawEmail) -> dict[str, Any]:
        seen.append(raw)
        return {"status": "completed", "task_status": "archived", "duplicate": False}

    res = sync_once(
        cfg, ingest or default, lambda h, p: server, now=datetime(2026, 11, 20, tzinfo=UTC)
    )
    return res, seen


def test_opens_mailbox_read_only_and_peeks(cfg: SyncConfig) -> None:
    server = FakeImap({1: eml("one")})
    res, seen = run(cfg, server)
    assert server.selected == ("INBOX", True)  # read-only select: nothing can be modified
    fetches = [c for c in server.calls if c[0] == "FETCH" and "BODY" in c[2]]
    assert fetches and all("PEEK" in c[2] for c in fetches)  # never marks mail as read
    assert not any(c[0] in ("STORE", "COPY", "EXPUNGE") for c in server.calls)
    assert res.ingested == 1 and seen[0].subject == "one" and seen[0].from_email == "anna@firma.de"
    assert server.logged_out


def test_profile_is_applied_and_state_is_saved(cfg: SyncConfig) -> None:
    _, seen = run(cfg, FakeImap({5: eml("a"), 6: eml("b")}))
    assert {r.profile for r in seen} == {Profile.PERSONAL}
    assert load_state(cfg.state_path) == {"uidvalidity": 7, "last_uid": 6}


def test_second_run_only_fetches_new_mail(cfg: SyncConfig) -> None:
    server = FakeImap({1: eml("a"), 2: eml("b")})
    run(cfg, server)
    server.messages[3] = eml("c")
    res, seen = run(cfg, server)
    assert [r.subject for r in seen] == ["c"] and res.last_uid == 3
    res2, seen2 = run(
        cfg, server
    )  # nothing new: the server echoes the last UID, which must be ignored
    assert res2.ingested == 0 and seen2 == []


def test_uidvalidity_change_resets_state(cfg: SyncConfig) -> None:
    run(cfg, FakeImap({1: eml("a")}, validity=7))
    res, seen = run(cfg, FakeImap({1: eml("renumbered")}, validity=8))
    assert [r.subject for r in seen] == ["renumbered"] and res.ingested == 1


def test_failed_ingest_stops_and_is_retried_next_time(cfg: SyncConfig) -> None:
    server = FakeImap({1: eml("a"), 2: eml("b"), 3: eml("c")})
    calls: list[str] = []

    def flaky(raw: RawEmail) -> dict[str, Any]:
        calls.append(raw.subject)
        if raw.subject == "b":
            raise RuntimeError("api down")
        return {"status": "completed", "task_status": "closed"}

    res, _ = run(cfg, server, flaky)
    assert (
        calls == ["a", "b"] and res.failed == 1 and res.last_uid == 1
    )  # stopped at b, did not skip it
    res2, seen = run(cfg, server)
    assert [r.subject for r in seen] == ["b", "c"] and res2.failed == 0


def test_max_per_run_and_oversize_messages(cfg: SyncConfig) -> None:
    cfg.max_per_run = 2
    server = FakeImap({1: eml("a"), 2: eml("huge"), 3: eml("c")}, sizes={2: MAX_MESSAGE_BYTES + 1})
    res, seen = run(cfg, server)
    assert res.fetched == 2 and res.skipped == 1 and [r.subject for r in seen] == ["a"]
    assert not any(
        c[0] == "FETCH" and c[1] == "2" and "BODY" in c[2] for c in server.calls
    )  # huge mail never downloaded


def test_unparsable_message_is_skipped_not_fatal(
    cfg: SyncConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    import opspilot.sync.imap_sync as mod

    real = mod.raw_from_eml
    monkeypatch.setattr(
        mod,
        "raw_from_eml",
        lambda b: (_ for _ in ()).throw(ValueError("bad")) if b"BADMAIL" in b else real(b),
    )
    res, seen = run(cfg, FakeImap({1: eml("BADMAIL"), 2: eml("good")}))
    assert res.skipped == 1 and [r.subject for r in seen] == ["good"]


def test_state_file_contains_no_secrets(cfg: SyncConfig) -> None:
    run(cfg, FakeImap({1: eml("a")}))
    text = cfg.state_path.read_text()
    assert "app-password" not in text and set(json.loads(text)) == {"uidvalidity", "last_uid"}


def test_config_requires_credentials() -> None:
    from opspilot.settings import Settings

    with pytest.raises(SystemExit):
        SyncConfig.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]
    s = Settings(_env_file=None, imap_user="me@example.org", imap_password="pw", imap_profile="ops")  # type: ignore[call-arg,arg-type]
    cfg = SyncConfig.from_settings(s)
    assert cfg.profile is Profile.OPS and cfg.password == "pw" and cfg.host == "imap.gmail.com"
