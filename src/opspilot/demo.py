"""`make demo-local`: one command, no Docker, no API key.

Starts an embedded Postgres (pgserver) unless DATABASE_URL is set, migrates, loads reference
data and the sample inbox, then serves the API (8000) and the dashboard (8501).
"""

import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

HOME = Path.home() / ".opspilot-demo"  # short path: Postgres unix-socket paths are length-limited
API_PORT, DASH_PORT = 8000, 8501


def _wait(url: str, timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except OSError:
            time.sleep(0.5)
    raise SystemExit(f"timed out waiting for {url}")


def main() -> None:
    env = dict(os.environ)
    server = None
    if "DATABASE_URL" not in env:
        import pgserver  # dev dependency; the Docker path does not need it

        HOME.mkdir(exist_ok=True)
        server = pgserver.get_server(  # type: ignore[attr-defined]
            HOME / "pg", cleanup_mode="stop"
        )
        env["DATABASE_URL"] = server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
        print(f"embedded Postgres ready in {HOME}")
    env.setdefault("OPSPILOT_API_KEY", "dev-key")
    env["OPSPILOT_API_URL"] = f"http://127.0.0.1:{API_PORT}"
    py = sys.executable

    subprocess.run([py, "-m", "opspilot.db.seed"], env=env, check=True)
    subprocess.run([py, "-m", "opspilot.demo_load", "--if-empty"], env=env, check=True)
    if not list(Path("reports").glob("eval_*.json")):
        subprocess.run([py, "-m", "opspilot.eval.run"], env=env, check=True)

    procs = [
        subprocess.Popen(
            [
                py,
                "-m",
                "uvicorn",
                "opspilot.api.app:create_app",
                "--factory",
                "--port",
                str(API_PORT),
            ],
            env=env,
        ),
        subprocess.Popen(
            [
                py,
                "-m",
                "streamlit",
                "run",
                "dashboard/app.py",
                "--server.port",
                str(DASH_PORT),
                "--server.headless",
                "true",
            ],
            env=env,
        ),
    ]
    from opspilot.settings import Settings

    cfg = Settings()
    try:
        _wait(f"http://127.0.0.1:{API_PORT}/health")
        if (
            cfg.imap_user and cfg.imap_password
        ):  # live mailbox connected: keep syncing new mail in the background
            procs.append(
                subprocess.Popen([py, "-m", "opspilot.sync.imap_sync", "--watch"], env=env)
            )
            print(
                f"  mailbox sync: watching {cfg.imap_user} ({cfg.imap_host}, read-only, every {cfg.sync_interval_seconds}s)"
            )
        _wait(f"http://127.0.0.1:{DASH_PORT}/_stcore/health")
        print(
            f"\n  OpsPilot is running\n  dashboard: http://localhost:{DASH_PORT}\n  API docs:  http://localhost:{API_PORT}/docs  (X-API-Key: {env['OPSPILOT_API_KEY']})\n  Ctrl-C to stop\n"
        )
        if os.environ.get("OPSPILOT_NO_BROWSER") != "1":
            webbrowser.open(f"http://localhost:{DASH_PORT}")
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()
        if server is not None:
            server.cleanup()


if __name__ == "__main__":
    main()
