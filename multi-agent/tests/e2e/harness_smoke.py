#!/usr/bin/env python3
"""
Headless harness-profile smoke test (plan item [0.4], issue #4).

Exercises the execution surface end-to-end against a running MAS API:
save a fully-mock blueprint -> create a session -> execute -> assert the
mock agent's answer comes back. No LLM, no Redis, no Temporal required.

Usage (server already running, e.g. `mas api dev --port 8002`):

    python tests/e2e/harness_smoke.py [--url http://localhost:8002]

Exits 0 on success. Stdlib-only so it runs in CI and bare dev boxes.
"""

import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

FIXTURE = pathlib.Path(__file__).parents[2] / "run" / "fixtures" / "harness_smoke.yml"
HEADERS = {
    "Content-Type": "application/json",
    "X-Authenticated-User": "harness-e2e",
}


def call(url: str, payload: dict | None = None, timeout: int = 60):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode())


def wait_for_health(base: str, attempts: int = 30) -> None:
    for _ in range(attempts):
        try:
            status, _ = call(f"{base}/api/health/")
            if status == 200:
                return
        except (urllib.error.URLError, ConnectionError):
            pass
        time.sleep(2)
    sys.exit(f"FAIL: API at {base} not healthy after {attempts * 2}s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8002")
    base = parser.parse_args().url.rstrip("/")

    wait_for_health(base)
    print(f"[1/4] API healthy at {base}")

    status, body = call(
        f"{base}/api/blueprints/blueprint.save",
        {"blueprintRaw": FIXTURE.read_text()},
    )
    assert status == 201 and body.get("status") == "success", f"save failed: {status} {body}"
    blueprint_id = body["blueprint_id"]
    print(f"[2/4] blueprint saved: {blueprint_id}")

    status, run_id = call(
        f"{base}/api/sessions/user.session.create",
        {"blueprintId": blueprint_id},
    )
    assert status == 200 and isinstance(run_id, str) and run_id, f"create failed: {status} {run_id}"
    print(f"[3/4] session created: {run_id}")

    status, result = call(
        f"{base}/api/sessions/user.session.execute",
        {"sessionId": run_id, "inputs": {"user_prompt": "hello harness"}, "stream": False},
        timeout=120,
    )
    text = json.dumps(result)
    assert status == 200, f"execute failed: {status} {text}"
    assert "Mock Agent" in text, f"mock agent answer missing from result: {text[:500]}"
    print("[4/4] execution returned the mock agent answer — smoke test PASSED")


if __name__ == "__main__":
    main()
