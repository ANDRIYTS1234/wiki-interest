# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""Trigger check for SKILL.md's description: does `claude -p` pick the skill for a query?

Same method as skill-creator's scripts/run_eval.py: the skill is registered as a project-level
command under a unique name, and a run counts as triggered when the model's first tool call is
Skill (or Read) naming it. Three things are done differently, each because it broke a measurement:

- Every run gets its own temporary project folder with its own .claude/. run_eval registers all
  parallel runs in one project, so the model sees several copies of the skill under different
  names, may pick another run's copy and is then counted as not triggered. And run_eval looks for
  the nearest .claude/ up the tree: started from a folder without one it wrote the command into
  ~/.claude/commands, where every Claude Code session on the machine could see and run it.
- Temporary folders live under one parent (<tmp>/wiki-interest-trigger-eval/) and are removed at
  the end; a run that was killed (e.g. the app was closed) leaves them behind, so every start
  first removes what an earlier run left. On Ctrl+C the live `claude -p` children are stopped.
  The script fails if any temporary command was left in ~/.claude/commands.
- The stream is read in a thread (select() on pipes does not work on Windows); files are UTF-8.

    uv run evals/trigger_eval.py --model claude-haiku-4-5-20251001 --out evals/trigger-runs/x.json
    uv run evals/trigger_eval.py --model claude-haiku-4-5-20251001 --description-file new.txt

Queries come from evals/triggers.yaml. --positive-control adds a query that names the skill
outright: if that does not trigger nearly always, the numbers are not trustworthy on this setup.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
PREFIX = "wiki-interest-trigger-"
WORK = Path(tempfile.gettempdir()) / "wiki-interest-trigger-eval"
LIVE: set[subprocess.Popen] = set()
POSITIVE_CONTROL = "Use the wiki-interest skill to check whether interest in chess is growing in German Wikipedia."


def claude_executable(explicit: str | None) -> str:
    if explicit:
        return explicit
    found = shutil.which("claude")
    if not found:
        sys.exit("claude CLI not found; pass --claude")
    if found.lower().endswith((".cmd", ".bat")):  # npm shim on Windows: call the real binary directly
        exe = Path(found).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if exe.is_file():
            return str(exe)
    return found


def skill_description(text: str) -> tuple[str, str]:
    m = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
    fields = dict(line.split(": ", 1) for line in m.group(1).splitlines()) if m else {}
    return fields["name"], fields["description"]


def run_once(claude: str, model: str, query: str, name: str, description: str, timeout: float) -> dict[str, Any]:
    """One `claude -p` run in a fresh project folder. Returns the first tool calls and the verdict."""
    unique = f"{PREFIX}{uuid.uuid4().hex[:8]}"
    WORK.mkdir(parents=True, exist_ok=True)
    project = Path(tempfile.mkdtemp(prefix="run-", dir=WORK))
    try:
        commands = project / ".claude" / "commands"
        commands.mkdir(parents=True)
        body = "\n  ".join(description.split("\n"))
        (commands / f"{unique}.md").write_text(
            f"---\ndescription: |\n  {body}\n---\n\n# {name}\n\nThis skill handles: {description}\n", encoding="utf-8"
        )
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        proc = subprocess.Popen(
            [claude, "-p", query, "--output-format", "stream-json", "--verbose", "--model", model],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=project, env=env,
        )
        LIVE.add(proc)
        lines: queue.Queue[bytes] = queue.Queue()

        def pump() -> None:
            for line in iter(proc.stdout.readline, b""):
                lines.put(line)

        threading.Thread(target=pump, daemon=True).start()
        tools: list[str] = []
        verdict, deadline = None, time.time() + timeout
        try:
            while verdict is None and time.time() < deadline:
                try:
                    raw = lines.get(timeout=1.0)
                except queue.Empty:
                    if proc.poll() is not None and lines.empty():
                        break
                    continue
                try:
                    event = json.loads(raw.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "assistant":
                    for item in event.get("message", {}).get("content", []):
                        if item.get("type") != "tool_use":
                            continue
                        args = item.get("input", {})
                        hit = (item["name"] == "Skill" and unique in str(args.get("skill", ""))) or (
                            item["name"] == "Read" and unique in str(args.get("file_path", ""))
                        )
                        tools.append(item["name"] + ("*" if hit else ""))
                        verdict = hit  # the first tool call decides, as in run_eval
                        break
                elif event.get("type") == "result":
                    verdict = False
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            LIVE.discard(proc)
        return {"triggered": bool(verdict), "first_tool": tools[0] if tools else None, "timed_out": verdict is None}
    finally:
        shutil.rmtree(project, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--description-file", help="test this description instead of SKILL.md's")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--positive-control", action="store_true")
    ap.add_argument("--claude")
    ap.add_argument("--out")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    name, description = skill_description((ROOT / "SKILL.md").read_text(encoding="utf-8"))
    if args.description_file:
        description = Path(args.description_file).read_text(encoding="utf-8").strip()
    if len(description) > 1024:
        sys.exit(f"description is {len(description)} characters; the limit is 1024")
    sets = yaml.safe_load((ROOT / "evals" / "triggers.yaml").read_text(encoding="utf-8"))
    queries = [(q, True) for q in sets["should_trigger"]] + [(q, False) for q in sets["should_not_trigger"]]
    if args.positive_control:
        queries.append((POSITIVE_CONTROL, True))
    claude = claude_executable(args.claude)

    shutil.rmtree(WORK, ignore_errors=True)  # leftovers of an interrupted earlier run
    jobs = [(q, expected) for q, expected in queries for _ in range(args.runs)]
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            outcomes = list(pool.map(lambda j: run_once(claude, args.model, j[0], name, description, args.timeout), jobs))
    except KeyboardInterrupt:
        for proc in list(LIVE):
            proc.kill()
        shutil.rmtree(WORK, ignore_errors=True)
        raise
    shutil.rmtree(WORK, ignore_errors=True)

    results = []
    for i, (q, expected) in enumerate(queries):
        runs = outcomes[i * args.runs : (i + 1) * args.runs]
        n = sum(r["triggered"] for r in runs)
        rate = n / len(runs)
        results.append({
            "query": q, "should_trigger": expected, "triggers": n, "runs": len(runs), "trigger_rate": rate,
            "pass": (rate > args.threshold) if expected else (rate <= args.threshold),
            "first_tools": [r["first_tool"] for r in runs], "timeouts": sum(r["timed_out"] for r in runs),
            "positive_control": q == POSITIVE_CONTROL,
        })

    leftovers = sorted(p.name for p in (Path.home() / ".claude" / "commands").glob(f"{PREFIX}*"))
    real = [r for r in results if not r["positive_control"]]
    pos = [r for r in real if r["should_trigger"]]
    neg = [r for r in real if not r["should_trigger"]]
    summary = {
        "model": args.model,
        "runs_per_query": args.runs,
        "should_trigger": f"{sum(r['triggers'] for r in pos)}/{sum(r['runs'] for r in pos)}",
        "should_not_trigger_false_positives": f"{sum(r['triggers'] for r in neg)}/{sum(r['runs'] for r in neg)}",
        "queries_passed": f"{sum(r['pass'] for r in real)}/{len(real)}",
        "positive_control": next((f"{r['triggers']}/{r['runs']}" for r in results if r["positive_control"]), None),
    }
    report = {"skill_name": name, "description": description, "summary": summary, "results": results}
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    if leftovers:
        print(f"ERROR: temporary commands left in ~/.claude/commands: {leftovers}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
