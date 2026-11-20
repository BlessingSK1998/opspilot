"""Read-only IMAP mailbox sync.

Polls a mailbox and sends each new message through OpsPilot's `/ingest`. It opens the folder
read-only and fetches with `BODY.PEEK[]`, so it never marks mail as read, and it never deletes,
moves or flags anything. The last processed UID is remembered in a small state file.
"""

import contextlib
import imaplib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import httpx

from opspilot.emailio import raw_from_eml
from opspilot.schemas.enums import Profile
from opspilot.schemas.state import RawEmail
from opspilot.settings import Settings, get_settings

log = logging.getLogger(__name__)
MAX_MESSAGE_BYTES = 10 * 1024 * 1024  # larger messages are skipped, not downloaded in full


class ImapLike(Protocol):
    def select(self, mailbox: str, readonly: bool) -> tuple[str, list[Any]]: ...
    def uid(self, command: str, *args: str) -> tuple[str, list[Any]]: ...
    def response(self, code: str) -> tuple[str, list[Any]]: ...
    def logout(self) -> tuple[str, list[Any]]: ...


@dataclass
class SyncConfig:
    host: str
    port: int
    user: str
    password: str
    folder: str = "INBOX"
    profile: Profile = Profile.PERSONAL
    since_days: int = 14
    max_per_run: int = 50
    state_path: Path = Path(".opspilot-sync.json")

    @classmethod
    def from_settings(cls, s: Settings) -> "SyncConfig":
        if not s.imap_user or s.imap_password is None:
            raise SystemExit("Set IMAP_USER and IMAP_PASSWORD in .env first (see .env.example).")
        return cls(s.imap_host, s.imap_port, s.imap_user, s.imap_password.get_secret_value(), s.imap_folder,
                   Profile(s.imap_profile), s.imap_since_days, s.imap_max_per_run, Path(s.sync_state_path))  # fmt: skip


@dataclass
class SyncResult:
    fetched: int = 0
    ingested: int = 0
    duplicates: int = 0
    skipped: int = 0
    failed: int = 0
    last_uid: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)


def load_state(path: Path) -> dict[str, int]:
    try:
        data = json.loads(path.read_text())
        return {"uidvalidity": int(data["uidvalidity"]), "last_uid": int(data["last_uid"])}
    except (OSError, ValueError, KeyError):
        return {}


def save_state(path: Path, uidvalidity: int, last_uid: int) -> None:
    path.write_text(json.dumps({"uidvalidity": uidvalidity, "last_uid": last_uid}))


def _uidvalidity(client: ImapLike) -> int:
    """UIDVALIDITY changes if the server renumbers the mailbox; stored UIDs are then meaningless."""
    _, data = client.response("UIDVALIDITY")
    try:
        return int(data[0])
    except (TypeError, ValueError, IndexError):
        return 0


def sync_once(
    cfg: SyncConfig,
    ingest: Callable[[RawEmail], dict[str, Any]],
    client_factory: Callable[[str, int], ImapLike] | None = None,
    now: datetime | None = None,
) -> SyncResult:
    """One pass: fetch mail newer than the last seen UID and ingest it, oldest first."""
    factory = client_factory or (lambda h, p: imaplib.IMAP4_SSL(h, p))
    client = factory(cfg.host, cfg.port)
    result = SyncResult()
    try:
        login = getattr(client, "login", None)
        if login is not None:
            login(cfg.user, cfg.password)
        typ, _ = client.select(cfg.folder, True)  # readonly=True: nothing can be changed
        if typ != "OK":
            raise RuntimeError(f"cannot open folder {cfg.folder!r}")
        validity = _uidvalidity(client)
        state = load_state(cfg.state_path)
        if state.get("uidvalidity") != validity:
            state = {}  # first run, or the server renumbered the mailbox
        last_uid = state.get("last_uid", 0)

        if last_uid:
            criteria = f"UID {last_uid + 1}:*"
        else:
            since = (now or datetime.now(UTC)) - timedelta(days=cfg.since_days)
            criteria = f"SINCE {since.strftime('%d-%b-%Y')}"
        typ, data = client.uid("SEARCH", criteria)
        uids = sorted(int(u) for u in (data[0] or b"").split()) if typ == "OK" and data else []
        uids = [u for u in uids if u > last_uid][: cfg.max_per_run]
        result.fetched = len(uids)

        for uid in uids:
            size_typ, size_data = client.uid("FETCH", str(uid), "(RFC822.SIZE)")
            if size_typ == "OK" and size_data and _size(size_data[0]) > MAX_MESSAGE_BYTES:
                result.skipped += 1
                last_uid = uid
                continue
            typ, msg = client.uid(
                "FETCH", str(uid), "(BODY.PEEK[])"
            )  # PEEK: does not mark the mail as read
            if typ != "OK" or not msg or not isinstance(msg[0], tuple):
                result.skipped += 1
                last_uid = uid
                continue
            try:
                raw = raw_from_eml(msg[0][1]).model_copy(update={"profile": cfg.profile})
            except Exception:  # an unparsable message must not block the mailbox
                log.warning("skipping unparsable message uid=%s", uid)
                result.skipped += 1
                last_uid = uid
                continue
            try:
                res = ingest(raw)
            except Exception as exc:
                log.warning("ingest failed for uid=%s (%s); will retry on the next run", uid, exc)
                result.failed += 1
                break  # keep order: do not advance past a message that was not ingested
            result.ingested += 1
            result.duplicates += bool(res.get("duplicate"))
            key = str(res.get("task_status") or res.get("status"))
            result.outcomes[key] = result.outcomes.get(key, 0) + 1
            last_uid = uid
        result.last_uid = last_uid
        save_state(cfg.state_path, validity, last_uid)
    finally:
        with contextlib.suppress(Exception):
            client.logout()
    return result


def _size(item: Any) -> int:
    text = item.decode() if isinstance(item, bytes) else str(item)
    marker = "RFC822.SIZE "
    if marker not in text:
        return 0
    digits = "".join(ch for ch in text.split(marker, 1)[1] if ch.isdigit())
    return int(digits) if digits else 0


def http_ingest(api_url: str, api_key: str) -> Callable[[RawEmail], dict[str, Any]]:
    def post(raw: RawEmail) -> dict[str, Any]:
        r = httpx.post(
            f"{api_url}/ingest",
            content=raw.model_dump_json(),
            headers={"X-API-Key": api_key, "content-type": "application/json"},
            timeout=300.0,
        )
        if (
            r.status_code == 503
        ):  # the LLM provider is down (e.g. out of credits): surface the reason
            raise RuntimeError(r.json().get("detail", "service unavailable"))
        r.raise_for_status()
        out: dict[str, Any] = r.json()
        return out

    return post


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Read-only IMAP sync into OpsPilot")
    ap.add_argument("--watch", action="store_true", help="keep polling")
    ap.add_argument(
        "--reset", action="store_true", help="forget the last-seen UID (re-fetch recent mail)"
    )
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    s = get_settings()
    cfg = SyncConfig.from_settings(s)
    if args.reset and cfg.state_path.exists():
        cfg.state_path.unlink()
    ingest = http_ingest(s.api_url, s.api_key.get_secret_value())
    failures = 0
    while True:
        try:
            r = sync_once(cfg, ingest)
            failures = failures + 1 if r.failed else 0
            print(
                f"sync: fetched {r.fetched}, ingested {r.ingested} (duplicates {r.duplicates}), skipped {r.skipped}, failed {r.failed}; outcomes {r.outcomes}"
            )
        except Exception as exc:  # network / auth problems: report, keep watching
            failures += 1
            print(f"sync error: {type(exc).__name__}: {exc}")
            if not args.watch:
                return 1
        if not args.watch:
            return 0
        # back off while ingestion keeps failing (e.g. the LLM provider is out of credits): 2x, 4x, ... up to 30 min
        time.sleep(min(s.sync_interval_seconds * (2 ** min(failures, 4)), 1800))


if __name__ == "__main__":
    raise SystemExit(main())
