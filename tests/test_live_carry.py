"""Carrying the plugin's state between Claude Cowork sessions: the probe (`TE_CARRY=probe`).

A Cowork container keeps nothing, and a hook cannot reach the person's computer; the model can,
through its PC shell tool. With the probe on, SessionStart asks the model to restore the saved
state, and every Stop asks it to save what is new since the last save, as one command it runs
as written. Off, nothing changes.
"""
import hashlib
import re

from test_live_hooks import call, env, repo, store_for  # noqa: F401 (fixtures)

BODY = re.compile(r"<<'TE_CARRY_END'\n(.*?)\nTE_CARRY_END\n", re.S)


def _turn(env, repo, sid, key, command):
    base = {"session_id": sid, "transcript_path": "", "cwd": repo, "prompt_id": key}
    call(env, dict(base, hook_event_name="UserPromptSubmit", prompt="go"))
    call(env, dict(base, hook_event_name="PostToolUse", tool_name="Bash",
                   tool_input={"command": command},
                   tool_response={"stdout": "ok", "stderr": "", "interrupted": False}))
    return call(env, dict(base, hook_event_name="Stop", stop_hook_active=False))


def _saved(out):
    """(file name, header, body) of the save a Stop answer asks for."""
    m = BODY.search(out["reason"])
    header, body = m.group(1).split("\n", 1)
    name = re.search(r'\.tokeneconomizer/(save-[^"]+\.txt)"', out["reason"]).group(1)
    return name, header, body + "\n"


def test_off_by_default_nothing_is_asked(env, repo):
    start = call(env, {"hook_event_name": "SessionStart", "session_id": "s", "cwd": repo,
                       "transcript_path": "", "source": "startup"})
    assert ".tokeneconomizer" not in str(start)
    assert "decision" not in _turn(env, repo, "s", "p1", "ls")


def test_the_start_asks_for_a_restore_into_the_state_root(env, repo):
    env = dict(env, TE_CARRY="probe")
    start = call(env, {"hook_event_name": "SessionStart", "session_id": "s", "cwd": repo,
                       "transcript_path": "", "source": "startup"})
    text = start["hookSpecificOutput"]["additionalContext"]
    assert "~/mnt/*/.tokeneconomizer/save-*.txt" in text
    root = env["TOKENECONOMIZER_HOME"].replace("\\", "/")
    assert f"{root}/carry/restored.txt" in text


def test_each_stop_asks_for_one_save_of_what_is_new_with_its_hash(env, repo):
    env = dict(env, TE_CARRY="probe")
    call(env, {"hook_event_name": "SessionStart", "session_id": "abcdef0123", "cwd": repo,
               "transcript_path": "", "source": "startup"})
    first = _turn(env, repo, "abcdef0123", "p1", "ls one")
    assert first["decision"] == "block"
    name1, header1, body1 = _saved(first)
    assert name1 == "save-abcdef01-001.txt"
    assert header1 == ("# te-carry v0 session=abcdef0123 n=1 sha256="
                       + hashlib.sha256(body1.encode()).hexdigest())
    assert all(ln.split("\t", 1)[0] in ("events.jsonl", "ledger.jsonl", "envelope.json")
               for ln in body1.splitlines())
    assert '"kind": "turn"' in body1
    # The save's own Stop is the model ending the asked-for turn: nothing more is asked.
    again = call(env, {"hook_event_name": "Stop", "session_id": "abcdef0123", "cwd": repo,
                       "transcript_path": "", "prompt_id": "p1", "stop_hook_active": True})
    assert "decision" not in again
    second = _turn(env, repo, "abcdef0123", "p2", "ls two")
    name2, _, body2 = _saved(second)
    assert name2 == "save-abcdef01-002.txt"
    assert '"kind": "carry_ask"' in body2            # the first ask, logged after its save
    # Only what is new: no log line again, and one learned turn each (the two turns are alike).
    logs1 = {ln for ln in body1.splitlines() if not ln.startswith("envelope.json")}
    assert logs1 and not logs1 & set(body2.splitlines())
    assert [ln[:13] for ln in body2.splitlines()].count("envelope.json") == 1
    asks = [e for e in store_for(env, repo).read_lines("events.jsonl")
            if e["kind"] == "carry_ask"]
    assert [a["n"] for a in asks] == [1, 2] and all(a["chars"] > 0 for a in asks)
