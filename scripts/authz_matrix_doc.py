"""Generates docs/authz-matrix.md from data/authz/matrix.yaml (the same file the tests run from).

Usage: uv run python scripts/authz_matrix_doc.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
ICON = {"allow": "✅", "deny": "⛔", "design": "🔑", "finding": "🐞"}


def cell(spec: Any) -> str:
    if spec is None:
        return "—"
    if isinstance(spec, int):
        return f"{ICON['allow' if spec < 400 else 'deny']} {spec}"
    if "finding" in spec:
        return f"{ICON['finding']} expect {spec['status']} ({spec['finding']})"
    return f"{ICON[spec.get('class', 'allow')]} {spec['status']}"


def main() -> None:
    matrix = yaml.safe_load((ROOT / "data" / "authz" / "matrix.yaml").read_text(encoding="utf-8"))
    roles = matrix["roles"]
    total = sum(len(op["expect"]) for op in matrix["operations"])
    lines = [
        "# Access matrix",
        "",
        "Generated from `data/authz/matrix.yaml` by `scripts/authz_matrix_doc.py`; the same file drives",
        f"`tests/authz/test_access_matrix.py` ({total} cases). Resources marked `_a` belong to customer A and are",
        "created for every case (or once per worker for read-only operations).",
        "",
        "Legend: ✅ allowed · ⛔ denied as expected · 🔑 allowed by design (the ID works as a capability, documented",
        "by Medusa) · 🐞 defect — the cell shows the correct outcome, the test is a strict xfail · — not tested.",
        "",
        "| Operation | " + " | ".join(roles) + " |",
        "|---|" + "---|" * len(roles),
    ]
    for op in matrix["operations"]:
        lines.append(f"| `{op['request']}` | " + " | ".join(cell(op["expect"].get(r)) for r in roles) + " |")
    lines += ["", "## Notes", ""]
    lines += [f"- **{op['id']}** — {op['note']}" for op in matrix["operations"] if op.get("note")]
    lines += [
        "",
        "## Design risks (not filed as defects)",
        "",
        "- Orders and carts are readable and editable by anyone who holds their ID. Medusa documents this for guest",
        "  checkout; the IDs are ULIDs with 80 random bits, so they cannot be guessed, but they must be treated as",
        "  secrets: they appear in URLs (order confirmation page) and can leak through logs, referrers or support",
        "  screenshots. An order ID exposes the customer's e-mail and shipping address.",
        "- Mitigation options for a real shop: require a second factor (e-mail) for guest order lookup, shorten",
        "  cart lifetime, and use Medusa's `validate` workflow hooks to enforce cart ownership.",
        "",
    ]
    (ROOT / "docs" / "authz-matrix.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"authz-matrix: {total} cases -> docs/authz-matrix.md")


if __name__ == "__main__":
    main()
