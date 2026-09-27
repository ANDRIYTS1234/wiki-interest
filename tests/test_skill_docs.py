"""SKILL.md and references/ must stay in sync with the CLI: flag codes, placeholder formats, frontmatter."""

from __future__ import annotations

import re
from pathlib import Path

from wiki_interest.analyze.quality import SEVERITY

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "SKILL.md", *sorted((ROOT / "references").glob("*.md"))]


def test_flag_table_matches_code():
    doc = (ROOT / "references" / "interpreting.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| ([A-Z][A-Z0-9_]+) \|", doc, flags=re.M))
    assert documented == set(SEVERITY)


def test_doc_placeholders_use_valid_formats():
    for path in DOCS:
        for ph_path, fmt in re.findall(r"\{([a-z_]+(?:\.[A-Za-z0-9_]+)+):([a-z]+)\}", path.read_text(encoding="utf-8")):
            assert fmt in {"pct", "int", "x", "ci"}, (path.name, ph_path, fmt)
            metric = ph_path.rsplit(".", 1)[-1]
            if fmt == "pct":
                assert metric in {"change_norm", "share_change"}, (path.name, ph_path)
            if metric in {"index_norm", "ratio"}:
                assert fmt == "x", (path.name, ph_path)


def test_skill_frontmatter():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
    assert m
    fields = dict(line.split(": ", 1) for line in m.group(1).splitlines())
    assert fields["name"] == "wiki-interest"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fields["name"]) and len(fields["name"]) <= 64
    assert 0 < len(fields["description"]) <= 1024
    assert len(fields.get("compatibility", "")) <= 500
    assert set(fields) <= {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
    for ref in re.findall(r"`(references/[a-z-]+\.md)`", text):
        assert (ROOT / ref).is_file(), ref
