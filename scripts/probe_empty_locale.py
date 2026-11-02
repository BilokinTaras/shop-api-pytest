"""SPEC-4 probe: which Store API operations reject an empty `locale` query parameter.

The spec declares `locale` as a plain string on most Store operations, so `locale=` is valid input; Medusa
2.22.2 answers 400 "Unrecognized fields: 'locale'" (a non-empty value is accepted). Schemathesis reaches a
different subset of these operations on each fresh stand, so the class is triaged here for every operation in
the scope of `make contract`, not one fuzzer hit at a time.

Each operation is called once with `?locale=`, the publishable key, no customer auth, placeholder path ids and
an empty JSON body for writes. Operations that answer 401, 404 HTML or a body validation error first cannot
produce this failure in the fuzzing run and are reported as unreachable.

Usage: uv run python scripts/probe_empty_locale.py [--update-baselines]   (needs a running stand)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "contracts" / "openapi" / "store.openapi.yaml"
# The two runs of `make contract` and which operations each one selects (see ST_STORE / ST_CARTS).
SCOPES = {
    "store": lambda method, path: method == "GET",
    "store-carts": lambda method, path: path.startswith("/store/carts"),
}
CHECK, FAILURE, SIGNATURE = "positive_data_acceptance", "RejectedPositiveData", "400"


def sut_value(key: str) -> str:
    if os.environ.get(key):
        return os.environ[key]
    env_file = Path(os.environ.get("SUT_ENV_FILE") or ROOT.parent / "shop-sut" / ".generated" / "sut.env")
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    sys.exit(f"{key} not set and not in {env_file}")


def operations(spec: dict[str, Any]) -> list[tuple[str, str]]:
    def declares_locale(params: list[dict[str, Any]]) -> bool:
        for raw in params:
            p = spec["components"]["parameters"][raw["$ref"].rsplit("/", 1)[-1]] if "$ref" in raw else raw
            if p.get("in") == "query" and p.get("name") == "locale":
                return True
        return False

    found = []
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method in {"get", "post", "delete"} and declares_locale(
                item.get("parameters", []) + op.get("parameters", [])
            ):
                found.append((method.upper(), path))
    return found


def entry_id(operation: str) -> str:
    return hashlib.sha256("\0".join((operation, CHECK, FAILURE, SIGNATURE)).encode()).hexdigest()[:6]


def main() -> None:
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    backend = sut_value("SUT_BACKEND_URL").rstrip("/")
    headers = {"x-publishable-api-key": sut_value("SUT_PUBLISHABLE_KEY")}
    rejected: dict[str, list[str]] = {scope: [] for scope in SCOPES}
    with httpx.Client(base_url=backend, headers=headers, timeout=15) as client:
        for method, path in operations(spec):
            scopes = [name for name, selects in SCOPES.items() if selects(method, path)]
            if not scopes:
                continue
            url = re.sub(r"\{[^}]+\}", "qa_probe_placeholder", path) + "?locale="
            response = client.request(method, url, json={} if method != "GET" else None)
            hit = response.status_code == 400 and "Unrecognized fields: 'locale'" in response.text
            print(f"{'rejects   ' if hit else 'unreachable'} {response.status_code} {method} {path}")
            for scope in scopes if hit else []:
                rejected[scope].append(f"{method} {path}")
    print(f"\nrejecting empty locale: {', '.join(f'{k} {len(v)}' for k, v in rejected.items())}")

    if "--update-baselines" not in sys.argv:
        return
    today = datetime.now(UTC).date().isoformat()
    for scope, ops in rejected.items():
        baseline = ROOT / "contracts" / f"schemathesis-baseline.{scope}.json"
        data = json.loads(baseline.read_text(encoding="utf-8"))
        known = {e["id"] for e in data["entries"]}
        added = [
            {
                "id": entry_id(op),
                "operation": op,
                "check": CHECK,
                "failure": FAILURE,
                "signature": SIGNATURE,
                "first_seen": today,
                "last_seen": today,
                "triage": "SPEC-4",
            }
            for op in ops
            if entry_id(op) not in known
        ]
        data["entries"] = sorted(
            data["entries"] + added, key=lambda e: (e["operation"], e["check"], e["signature"])
        )
        baseline.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        print(f"{baseline.name}: +{len(added)}")


if __name__ == "__main__":
    main()
