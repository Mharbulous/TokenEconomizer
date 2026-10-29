"""A fixed envelope (`loopguard.envelope_frozen`): the guard acts before a repository has learned
its own, as in a Claude Cowork session, whose container keeps nothing between sessions."""
import json

import pytest

from tests.test_live_hooks import _fake_judges, _first, _turn, env, repo, stuck_calls  # noqa: F401
from tokeneconomizer.loopguard import load_envelope, thresholds
from tokeneconomizer.plugin.config import LiveConfig


class _Store:
    def __init__(self, envelope=None):
        self.envelope = envelope

    def read(self, name):
        return self.envelope if name == "envelope.json" else None


def test_a_frozen_envelope_is_used_before_any_turn_is_learned():
    pinned = {"envelope_frozen": 38}
    tracker = load_envelope(_Store(), overrides=pinned)
    assert tracker.envelope == 38
    thr = thresholds(tracker, pinned)
    assert thr["backstop_turns"] == 95
    assert "envelope_frozen" not in thr


def test_a_learned_envelope_wins_once_there_is_one():
    tracker = load_envelope(_Store({"resolved_turns": [8] * 5}), overrides={"envelope_frozen": 38})
    assert tracker.envelope == 10              # 1.25 x the 90th percentile of 8


def test_unset_there_is_no_envelope_before_learning():
    assert load_envelope(_Store()).envelope is None


@pytest.mark.parametrize("value", [0, -1, "x"])
def test_the_setting_refuses_what_is_not_a_positive_number(value):
    cfg = LiveConfig()
    assert cfg.set("loopguard.envelope_frozen", value) is False
    assert "envelope_frozen" not in cfg.loopguard_thresholds


def test_the_setting_takes_a_positive_number():
    cfg = LiveConfig()
    assert cfg.set("loopguard.envelope_frozen", "38") is True
    assert cfg.loopguard_thresholds["envelope_frozen"] == 38.0


def test_with_a_frozen_envelope_a_cold_repository_reaches_the_judge(env, repo, monkeypatch):
    seen = []
    _fake_judges(monkeypatch, seen)
    frozen = dict(env, TE_LOOPGUARD_THRESHOLDS=json.dumps({"envelope_frozen": 38}))
    outs = _turn(frozen, repo, "s", "stuck", stuck_calls(40))
    assert seen
    assert _first(outs, lambda o: "hookSpecificOutput" in o) is not None
