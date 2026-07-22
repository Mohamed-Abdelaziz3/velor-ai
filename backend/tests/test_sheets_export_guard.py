import brain
from workers.sheets_worker import sync_lead_to_sheets


def test_google_sheets_export_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_GOOGLE_SHEETS_EXPORT", raising=False)

    assert brain._google_sheets_export_enabled() is False
    assert sync_lead_to_sheets("Private Name", "01000000000", "Private Interest", "tenant") == {
        "status": "skipped",
        "reason": "export_disabled",
    }


def test_google_sheets_export_requires_exact_true_opt_in(monkeypatch):
    for value in ("1", "yes", "enabled", "false", " true-ish "):
        monkeypatch.setenv("ENABLE_GOOGLE_SHEETS_EXPORT", value)
        assert brain._google_sheets_export_enabled() is False

    monkeypatch.setenv("ENABLE_GOOGLE_SHEETS_EXPORT", " TrUe ")
    assert brain._google_sheets_export_enabled() is True
