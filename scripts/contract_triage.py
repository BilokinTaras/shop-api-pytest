"""Classifies every accepted Schemathesis failure (contracts/schemathesis-baseline.*.json) into a triage
category and writes the generated part of docs/contract-findings.md.

Usage: uv run python scripts/contract_triage.py
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "contract-findings.md"
MARK = "<!-- generated: triage table -->"


def classify(entry: dict[str, str]) -> tuple[str, str]:
    check, signature = entry["check"], entry["signature"]
    if check == "not_a_server_error":
        return "Product defect (5xx)", "BUG-API-001 / 004 / 007 / 008 — see the reproduction table"
    if check == "response_schema_conformance":
        if signature.endswith("/type"):
            return "Spec defect", "SPEC-1: nullable property not marked `nullable`"
        if signature.endswith("/required"):
            return "Spec defect", "SPEC-2: property marked required is not always returned"
        return "Spec defect", "SPEC-3: response shape differs from the schema"
    if check == "positive_data_acceptance":
        return "Spec defect", "SPEC-4: documented input rejected by the API"
    if check == "negative_data_rejection":
        return "Spec defect", "SPEC-5: API accepts input the schema forbids (e.g. `null` objects)"
    if check == "content_type_conformance":
        if signature.startswith("text/html"):
            return "Spec defect", "SPEC-6: documented endpoint not present in this build (404 HTML)"
        return "Spec defect", "SPEC-7: 401 documented as text/plain, API returns JSON"
    if check in {"unsupported_method", "allow_header_conformance"}:
        return "Accepted behaviour", "ACC-1: undeclared HTTP methods get 404 from Express instead of 405"
    if check == "status_code_conformance":
        return (
            "False positive",
            "FP-1: oversized generated header rejected by Node's parser (431) before Medusa",
        )
    return "Unclassified", "needs review"


def main() -> None:
    rows: list[tuple[str, str, str, str]] = []
    for baseline in sorted((ROOT / "contracts").glob("schemathesis-baseline.*.json")):
        run = baseline.stem.removeprefix("schemathesis-baseline.")
        for entry in json.loads(baseline.read_text(encoding="utf-8"))["entries"]:
            category, reason = classify(entry)
            rows.append((run, entry["operation"], category, reason))

    by_reason = Counter((category, reason) for _, _, category, reason in rows)
    operations: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    for _, operation, category, reason in rows:
        operations[(category, reason)].add(operation)

    lines = [
        MARK,
        "",
        f"Accepted failures: **{len(rows)}** across {len({r[0] for r in rows})} runs "
        f"({', '.join(sorted({r[0] for r in rows}))}). Unclassified: "
        f"**{sum(n for (c, _), n in by_reason.items() if c == 'Unclassified')}**.",
        "",
        "| Category | Triage | Failures | Operations |",
        "|---|---|---:|---|",
    ]
    for (category, reason), count in sorted(by_reason.items(), key=lambda kv: (kv[0][0], -kv[1])):
        ops = sorted(operations[(category, reason)])
        shown = ", ".join(f"`{o}`" for o in ops[:6]) + (f" and {len(ops) - 6} more" if len(ops) > 6 else "")
        lines.append(f"| {category} | {reason} | {count} | {shown} |")
    generated = "\n".join(lines) + "\n"

    text = DOC.read_text(encoding="utf-8")
    head = text.split(MARK)[0]
    DOC.write_text(head + generated, encoding="utf-8")
    print(f"contract-triage: {len(rows)} failures classified -> {DOC.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
