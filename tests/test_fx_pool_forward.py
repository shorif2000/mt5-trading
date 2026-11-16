"""FX pool forward plumbing: freeze detection, signal tagging, row merge, loader."""

from pathlib import Path

from trading.research.fx_pool_forward import FxPoolInputs, digest, freeze_mismatches


def test_a_changed_frozen_file_is_reported(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("rule.md").write_text("fixed", encoding="utf-8")
    record = tmp_path / "freeze.json"
    import json

    record.write_text(json.dumps({"files": digest(["rule.md"])}), encoding="utf-8")
    assert freeze_mismatches(record) == []
    Path("rule.md").write_text("tuned", encoding="utf-8")
    assert freeze_mismatches(record) == ["rule.md"]


def test_loader_resolves_all_four_series_with_real_contract_specs():
    inp = FxPoolInputs()
    for symbol, digits in (("EURUSD", 5), ("GBPUSD", 5), ("USDJPY", 3)):
        assert len(inp.m15(symbol)) > 90000
        from trading.research.fx_pool_forward import SPECS

        assert SPECS[symbol].digits == digits
    assert len(inp.m15("GBPJPY")) > 90000
    assert all(v == 0 for v in inp.sizing.commission_per_lot.values())
