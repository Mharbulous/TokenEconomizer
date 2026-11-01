"""Carrying the plugin's state between Claude Cowork sessions: the probe (`TE_CARRY=probe`).

A Cowork container keeps nothing, and a hook cannot reach the person's computer; the model can,
through its PC shell tool. With the probe on, a session's first prompt asks the model to restore
the saved state, and every later prompt asks it to save what is new since the last ask, as one
command it runs as written, before it replies. Stop and SessionStart ask nothing. Off, nothing
changes.
"""
import hashlib
import re

from test_live_hooks import call, env, repo, store_for  # noqa: F401 (fixtures)

BODY = re.compile(r"<<'TE_CARRY_END'\n(.*?)\nTE_CARRY_END\n", re.S)


def _turn(env, repo, sid, key, command):
    """(UserPromptSubmit answer, Stop answer) of one prompt-turn with one shell call."""
    base = {"session_id": sid, "transcript_path": "", "cwd": repo, "prompt_id": key}
    prompt = call(env, dict(base, hook_event_name="UserPromptSubmit", prompt="go"))
    call(env, dict(base, hook_event_name="PostToolUse", tool_name="Bash",
                   tool_input={"command": command},
                   tool_response={"stdout": "ok", "stderr": "", "interrupted": False}))
    return prompt, call(env, dict(base, hook_event_name="Stop", stop_hook_active=False))


def _context(out):
    return out["hookSpecificOutput"]["additionalContext"]


def _saved(out):
    """(file name, header, body) of the save a prompt's answer asks for."""
    text = _context(out)
    m = BODY.search(text)
    header, body = m.group(1).split("\n", 1)
    name = re.search(r'\.tokeneconomizer/(save-[^"]+\.txt)"', text).group(1)
    return name, header, body + "\n"


def _start(env, repo, sid):
    return call(env, {"hook_event_name": "SessionStart", "session_id": sid, "cwd": repo,
                      "transcript_path": "", "source": "startup"})


def test_off_by_default_nothing_is_asked(env, repo):
    assert ".tokeneconomizer" not in str(_start(env, repo, "s"))
    for key in ("p1", "p2"):
        prompt, stop = _turn(env, repo, "s", key, "ls " + key)
        assert ".tokeneconomizer" not in str(prompt)
        assert "decision" not in stop


def test_the_first_prompt_asks_for_a_restore_into_the_state_root(env, repo):
    env = dict(env, TE_CARRY="probe")
    assert ".tokeneconomizer" not in str(_start(env, repo, "s"))
    prompt, stop = _turn(env, repo, "s", "p1", "ls")
    text = _context(prompt)
    assert "~/mnt/*/.tokeneconomizer/save-*.txt" in text
    assert "<<'TE_CARRY_END'" not in text             # a restore, not a save
    root = env["TOKENECONOMIZER_HOME"].replace("\\", "/")
    assert f"{root}/carry/restored.txt" in text
    assert "decision" not in stop


def test_each_later_prompt_asks_for_one_save_of_what_is_new_with_its_hash(env, repo):
    env = dict(env, TE_CARRY="probe")
    _start(env, repo, "abcdef0123")
    _turn(env, repo, "abcdef0123", "p1", "ls one")
    first, stop = _turn(env, repo, "abcdef0123", "p2", "ls two")
    assert "decision" not in stop
    name1, header1, body1 = _saved(first)
    assert name1 == "save-abcdef01-001.txt"
    assert header1 == ("# te-carry v0 session=abcdef0123 n=1 sha256="
                       + hashlib.sha256(body1.encode()).hexdigest())
    assert "te-carry: saved n=1" in _context(first)
    assert "Before you reply" in _context(first)
    assert all(ln.split("\t", 1)[0] in ("events.jsonl", "ledger.jsonl", "envelope.json")
               for ln in body1.splitlines())
    assert '"kind": "turn"' in body1                  # the first turn, closed at its Stop
    second, _ = _turn(env, repo, "abcdef0123", "p3", "ls three")
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
