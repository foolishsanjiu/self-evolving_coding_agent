import sys

import pytest

from evodev import smoke_llm


def test_smoke_paid_confirmation_is_required() -> None:
    with pytest.raises(PermissionError, match="--confirm-paid"):
        smoke_llm.require_smoke_paid_confirmation(False)
    smoke_llm.require_smoke_paid_confirmation(True)


def test_smoke_help_exits_without_loading_settings(monkeypatch, capsys) -> None:
    def unexpected_load(*args, **kwargs):
        raise AssertionError("--help must not load settings or call a provider")

    monkeypatch.setattr(smoke_llm, "load_settings", unexpected_load)
    monkeypatch.setattr(sys, "argv", ["evodev-smoke-llm", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        smoke_llm.main()

    assert exc_info.value.code == 0
    assert "--confirm-paid" in capsys.readouterr().out


def test_smoke_rejects_unconfirmed_call_before_loading_settings(monkeypatch) -> None:
    def unexpected_load(*args, **kwargs):
        raise AssertionError("unconfirmed smoke call must stop before loading settings")

    monkeypatch.setattr(smoke_llm, "load_settings", unexpected_load)
    monkeypatch.setattr(sys, "argv", ["evodev-smoke-llm"])

    with pytest.raises(PermissionError, match="--confirm-paid"):
        smoke_llm.main()
