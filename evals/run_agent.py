# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.31", "pyyaml>=6"]
# ///
"""Minimal agent loop over OpenRouter for evals/scenarios.yaml: with the skill or without (baseline).

One tool: `shell` (bash, run in a fresh sandbox folder). The system prompt is the scenario
preamble, plus SKILL.md when --mode skill. Scenario turns are sent in order; when the model ends a
turn with a question and no scripted turns are left, --auto-reply answers it (up to
--max-auto-replies times), since the skill asks the user to confirm the basket.

Every run writes evals/runs/<utc>_<scenario>_<mode>_<model>/:
  events.jsonl   every model call (tokens, seconds) and tool call (command, exit, output, seconds)
  transcript.md  readable conversation
  summary.json   model, mode, steps, tokens, cost, wall time, stop reason, final answer, and the
                 scenario checks with "result": null for manual grading
  sandbox/       the agent's working folder (out/report.pdf etc.)

The model runs real shell commands on this machine. Use a disposable VM or container.

    export OPENROUTER_API_KEY=...
    uv run evals/run_agent.py --scenario B --mode skill --model anthropic/claude-haiku-4.5
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import requests

EVALS = Path(__file__).resolve().parent
SKILL_DIR = EVALS.parent
API_URL = "https://openrouter.ai/api/v1/chat/completions"
OUTPUT_LIMIT = 12_000
DEFAULT_AUTO_REPLY = (
    "Так, погоджуюсь. Продовжуй на свій розсуд і доведи до кінця, включно з PDF-звітом, якщо він потрібен."
)

SHELL_TOOL = {
    "type": "function",
    "function": {
        "name": "shell",
        "description": (
            "Run a bash command in the working folder and return exit code, stdout and stderr "
            "(long output is truncated in the middle). State does not persist between calls except files."
        ),
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "bash command"}},
            "required": ["command"],
        },
    },
}


def load_scenario(scenario_id: str, path: Path = EVALS / "scenarios.yaml") -> tuple[str, dict[str, Any], list[dict]]:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for sc in data["scenarios"]:
        if str(sc["id"]) == scenario_id:
            return data["preamble"], sc, data.get("common_checks", [])
    raise SystemExit(f"scenario {scenario_id!r} not in {path}; known: {[s['id'] for s in data['scenarios']]}")


def system_prompt(preamble: str, mode: str) -> str:
    if mode == "baseline":
        return preamble.strip()
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    return (
        f"{preamble.strip()}\n\n"
        f"You have the Agent Skill below. SKILL_DIR={SKILL_DIR.as_posix()} (also set as the environment "
        f"variable $SKILL_DIR). Other skill files can be read with the shell tool.\n\n{skill}"
    )


def truncate(text: str, limit: int = OUTPUT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n... [{len(text) - limit} characters truncated] ...\n{text[-half:]}"


def run_shell(command: str, cwd: Path, timeout: float, env: dict[str, str]) -> dict[str, Any]:
    bash = shutil.which("bash")
    start = time.monotonic()
    try:
        proc = subprocess.run(
            [bash, "-c", command] if bash else command,
            shell=bash is None, cwd=cwd, env=env, capture_output=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        result = {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        result = {"exit_code": None, "stdout": out, "stderr": f"timed out after {timeout:.0f} s"}
    result["seconds"] = round(time.monotonic() - start, 2)
    return result


def tool_output(result: dict[str, Any]) -> str:
    return truncate(
        f"exit_code: {result['exit_code']}\n--- stdout ---\n{result['stdout']}\n--- stderr ---\n{result['stderr']}"
    )


def openrouter_chat(api_key: str, model: str, temperature: float | None) -> Callable[[list[dict]], dict]:
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/ANDRIYTS1234/wiki-interest",
        "X-Title": "wiki-interest evals",
    })

    def chat(messages: list[dict]) -> dict:
        body: dict[str, Any] = {"model": model, "messages": messages, "tools": [SHELL_TOOL], "usage": {"include": True}}
        if temperature is not None:
            body["temperature"] = temperature
        for attempt in range(6):
            try:
                resp = session.post(API_URL, json=body, timeout=300)
            except requests.RequestException as e:
                err = str(e)
            else:
                if resp.status_code == 200:
                    data = resp.json()
                    if "choices" in data:
                        return data
                    err = json.dumps(data.get("error", data))[:500]
                elif resp.status_code in (429, 500, 502, 503, 504):
                    err = f"HTTP {resp.status_code}: {resp.text[:300]}"
                else:
                    raise RuntimeError(f"OpenRouter HTTP {resp.status_code}: {resp.text[:1000]}")
            wait = min(60, 2 ** (attempt + 1))
            print(f"[run_agent] {err}; retry in {wait} s", file=sys.stderr)
            time.sleep(wait)
        raise RuntimeError(f"OpenRouter failed after retries: {err}")

    return chat


def asks_user(text: str) -> bool:
    tail = text.strip()[-400:]
    return "?" in tail


class Run:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.sandbox = folder / "sandbox"
        self.sandbox.mkdir(parents=True)
        self._events = (folder / "events.jsonl").open("a", encoding="utf-8")
        self._md = (folder / "transcript.md").open("a", encoding="utf-8")

    def event(self, **kw: Any) -> None:
        kw["t"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        self._events.write(json.dumps(kw, ensure_ascii=False) + "\n")
        self._events.flush()

    def md(self, text: str) -> None:
        self._md.write(text + "\n\n")
        self._md.flush()

    def close(self) -> None:
        self._events.close()
        self._md.close()


def agent_loop(
    run: Run,
    chat: Callable[[list[dict]], dict],
    system: str,
    turns: list[str],
    *,
    max_steps: int,
    max_seconds: float,
    command_timeout: float,
    auto_reply: str,
    max_auto_replies: int,
    env: dict[str, str],
) -> dict[str, Any]:
    messages: list[dict] = [{"role": "system", "content": system}]
    pending = list(turns)
    tokens = {"prompt": 0, "completion": 0}
    cost = 0.0
    steps = tool_calls = auto_replies = 0
    final_answer = ""
    answers: list[str] = []
    start = time.monotonic()
    stop = "done"

    def user(text: str, kind: str) -> None:
        messages.append({"role": "user", "content": text})
        run.event(type="user", kind=kind, content=text)
        run.md(f"## User ({kind})\n\n{text}")

    user(pending.pop(0), "scenario")
    while True:
        if steps >= max_steps:
            stop = "max_steps"
            break
        if time.monotonic() - start > max_seconds:
            stop = "max_time"
            break
        t0 = time.monotonic()
        try:
            data = chat(messages)
        except (RuntimeError, KeyboardInterrupt) as e:
            stop = f"error: {e!r}"[:500]
            run.event(type="error", step=steps + 1, error=stop)
            break
        steps += 1
        usage = data.get("usage") or {}
        tokens["prompt"] += usage.get("prompt_tokens") or 0
        tokens["completion"] += usage.get("completion_tokens") or 0
        cost += usage.get("cost") or 0.0
        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        content = msg.get("content") or ""
        run.event(type="model", step=steps, seconds=round(time.monotonic() - t0, 2), usage=usage,
                  finish_reason=data["choices"][0].get("finish_reason"), content=content,
                  tool_calls=[c["function"] for c in calls])
        assistant = {"role": "assistant", "content": content}
        if calls:
            assistant["tool_calls"] = calls
        messages.append(assistant)
        if content:
            run.md(f"## Assistant (step {steps})\n\n{content}")
        if calls:
            for call in calls:
                tool_calls += 1
                try:
                    command = json.loads(call["function"].get("arguments") or "{}")["command"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    command = None
                if call["function"].get("name") != "shell" or not isinstance(command, str):
                    result = {"exit_code": None, "stdout": "", "stderr": "invalid tool call: use shell with {\"command\": \"...\"}", "seconds": 0}
                else:
                    result = run_shell(command, run.sandbox, command_timeout, env)
                run.event(type="tool", step=steps, command=command, **result)
                run.md(f"```bash\n{command}\n```\n\nexit {result['exit_code']}, {result['seconds']} s\n\n"
                       f"```\n{truncate(result['stdout'] + result['stderr'], 3000)}\n```")
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": tool_output(result)})
            continue
        final_answer = content
        answers.append(content)
        if pending:
            user(pending.pop(0), "scenario")
        elif asks_user(content) and auto_replies < max_auto_replies:
            auto_replies += 1
            user(auto_reply, "auto_reply")
        else:
            break
    return {
        "stop_reason": stop,
        "steps": steps,
        "tool_calls": tool_calls,
        "auto_replies": auto_replies,
        "unsent_turns": len(pending),
        "tokens": tokens,
        "cost_usd": round(cost, 6),
        "seconds": round(time.monotonic() - start, 1),
        "final_answer": final_answer,
        "answers": answers,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--scenario", required=True, help="id from evals/scenarios.yaml (A, B, C, D, E)")
    p.add_argument("--model", required=True, help="OpenRouter model id, e.g. anthropic/claude-haiku-4.5")
    p.add_argument("--mode", choices=("skill", "baseline"), default="skill")
    p.add_argument("--max-steps", type=int, default=80, help="model calls per run")
    p.add_argument("--max-minutes", type=float, default=45)
    p.add_argument("--command-timeout", type=float, default=900, help="seconds per shell command")
    p.add_argument("--auto-reply", default=DEFAULT_AUTO_REPLY)
    p.add_argument("--max-auto-replies", type=int, default=3)
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("--runs-dir", type=Path, default=EVALS / "runs")
    args = p.parse_args(argv)

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY is not set", file=sys.stderr)
        return 2
    preamble, scenario, common = load_scenario(args.scenario)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", args.model)
    run = Run(args.runs_dir / f"{stamp}_{args.scenario}_{args.mode}_{slug}")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    env.pop("OPENROUTER_API_KEY", None)
    if args.mode == "skill":
        env["SKILL_DIR"] = SKILL_DIR.as_posix()
    system = system_prompt(preamble, args.mode)
    run.event(type="start", scenario=args.scenario, mode=args.mode, model=args.model, system=system)
    print(f"[run_agent] {run.folder}", file=sys.stderr)

    result = agent_loop(
        run, openrouter_chat(api_key, args.model, args.temperature), system,
        [str(t) for t in scenario["turns"]],
        max_steps=args.max_steps, max_seconds=args.max_minutes * 60,
        command_timeout=args.command_timeout, auto_reply=args.auto_reply,
        max_auto_replies=args.max_auto_replies, env=env,
    )
    error = result["stop_reason"] if result["stop_reason"].startswith("error") else None
    run.event(type="end", error=error, **{k: v for k, v in result.items() if k != "answers"})
    summary = {
        "scenario": args.scenario, "name": scenario.get("name"), "mode": args.mode, "model": args.model,
        "started_utc": stamp, "error": error, **result,
        "checks": [{**c, "result": None} for c in [*common, *scenario.get("checks", [])]],
    }
    (run.folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    run.close()
    print(json.dumps({k: summary.get(k) for k in ("stop_reason", "steps", "tool_calls", "tokens", "cost_usd", "seconds", "error")}))
    print(f"[run_agent] log: {run.folder}", file=sys.stderr)
    return 0 if error is None else 1


if __name__ == "__main__":
    sys.exit(main())
