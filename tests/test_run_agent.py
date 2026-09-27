"""evals/run_agent.py agent loop with a scripted fake model: no network, no API key."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parent.parent / "evals" / "run_agent.py"
spec = importlib.util.spec_from_file_location("run_agent", PATH)
run_agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_agent)

posix_shell = pytest.mark.skipif(sys.platform == "win32", reason="bash on Windows runners may be the WSL stub")


def reply(content="", command=None, usage=(10, 5)):
    msg = {"role": "assistant", "content": content}
    if command is not None:
        msg["tool_calls"] = [{"id": "c1", "type": "function",
                              "function": {"name": "shell", "arguments": json.dumps({"command": command})}}]
    return {"choices": [{"message": msg, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1], "cost": 0.001}}


def loop(tmp_path, script, turns, **kw):
    seen = []

    def chat(messages):
        seen.append([dict(m) for m in messages])
        return script.pop(0)

    run = run_agent.Run(tmp_path / "run")
    opts = dict(max_steps=20, max_seconds=60, command_timeout=30, auto_reply="ok",
                max_auto_replies=1, env=dict(os.environ))
    opts.update(kw)
    result = run_agent.agent_loop(run, chat, "system", turns, **opts)
    run.close()
    return run, result, seen


@posix_shell
def test_tool_call_runs_in_sandbox_and_output_goes_back(tmp_path):
    script = [reply(command="echo 'Сузір’я' > f.txt && cat f.txt"), reply("Готово.")]
    run, result, seen = loop(tmp_path, script, ["go"])
    assert (run.sandbox / "f.txt").read_text(encoding="utf-8").strip() == "Сузір’я"
    tool_msg = seen[1][-1]
    assert tool_msg["role"] == "tool" and "Сузір’я" in tool_msg["content"] and "exit_code: 0" in tool_msg["content"]
    assert result["stop_reason"] == "done" and result["steps"] == 2 and result["tool_calls"] == 1
    assert result["tokens"] == {"prompt": 20, "completion": 10}
    assert result["final_answer"] == "Готово."
    events = [json.loads(l) for l in (run.folder / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e["type"] for e in events] == ["user", "model", "tool", "model"]


def test_scripted_turns_then_one_auto_reply(tmp_path):
    script = [reply("Перша відповідь."), reply("Погоджуєте кошик?"), reply("Ще питання?")]
    _, result, seen = loop(tmp_path, script, ["turn 1", "turn 2"])
    users = [m["content"] for m in seen[-1] if m["role"] == "user"]
    assert users == ["turn 1", "turn 2", "ok"]
    assert result["auto_replies"] == 1 and result["answers"][-1] == "Ще питання?"


@posix_shell
def test_step_limit(tmp_path):
    script = [reply(command="true") for _ in range(5)]
    _, result, _ = loop(tmp_path, script, ["go"], max_steps=3)
    assert result["stop_reason"] == "max_steps" and result["steps"] == 3


def test_api_error_keeps_partial_stats(tmp_path):
    def chat_fail(messages):
        raise RuntimeError("OpenRouter HTTP 401")
    run = run_agent.Run(tmp_path / "run")
    result = run_agent.agent_loop(run, chat_fail, "s", ["go"], max_steps=5, max_seconds=60, command_timeout=5,
                                  auto_reply="ok", max_auto_replies=0, env=dict(os.environ))
    run.close()
    assert result["stop_reason"].startswith("error") and "401" in result["stop_reason"] and result["steps"] == 0


def test_bad_tool_arguments_are_reported_to_model(tmp_path):
    bad = reply()
    bad["choices"][0]["message"]["tool_calls"] = [
        {"id": "c1", "type": "function", "function": {"name": "shell", "arguments": "{not json"}}]
    _, result, seen = loop(tmp_path, [bad, reply("done")], ["go"])
    assert "invalid tool call" in seen[1][-1]["content"]
    assert result["stop_reason"] == "done"


def test_system_prompt_modes():
    assert run_agent.system_prompt("pre", "baseline") == "pre"
    with_skill = run_agent.system_prompt("pre", "skill")
    assert with_skill.startswith("pre") and "name: wiki-interest" in with_skill and "SKILL_DIR=" in with_skill


def test_load_scenario_ids():
    pytest.importorskip("yaml")
    preamble, sc, common = run_agent.load_scenario("B")
    assert preamble and sc["turns"] and common
