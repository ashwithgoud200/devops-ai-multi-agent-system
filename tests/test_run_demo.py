import builtins

from run_demo import _approval_decision


def test_demo_requires_explicit_approval_by_default(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda prompt: "reject")

    assert _approval_decision() is False


def test_demo_only_approves_after_explicit_operator_confirmation(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda prompt: "approve")

    assert _approval_decision() is True
    assert _approval_decision(approve=True) is True
    assert _approval_decision(reject=True) is False
