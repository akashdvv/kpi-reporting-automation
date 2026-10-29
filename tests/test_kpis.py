import importlib.util
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kpi.pipeline import Period, compute, load_config, load_sources, rag, validate  # noqa: E402

spec = importlib.util.spec_from_file_location("generate", ROOT / "data" / "generate.py")
generate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate)


@pytest.fixture(scope="module")
def src(tmp_path_factory):
    raw = tmp_path_factory.mktemp("raw")
    generate.main(out=raw)
    cfg = load_config()
    return cfg, load_sources(cfg, raw)


def test_sources_are_standardised(src):
    cfg, s = src
    assert set(s["tickets"].team) == {"Support"} and set(s["tasks"].team) == {"Delivery"}
    assert set(s["timesheets"].team) == {"Support", "Delivery"}
    assert s["tasks"].task_id.str.startswith("DLV-").all()       # header block above the table was skipped


def test_all_data_checks_pass_on_clean_sources(src):
    cfg, s = src
    assert (validate(s, cfg).status == "PASS").all()


def test_validation_catches_an_unmapped_team(src):
    cfg, s = src
    bad = dict(s)
    bad["timesheets"] = s["timesheets"].assign(team=lambda d: d.team.where(d.index > 0, "Ops"))
    out = validate(bad, cfg)
    assert out.loc[out.check.str.contains("team names"), "status"].item() == "FAIL"


def test_kpis_match_independent_pandas_calculation(src):
    cfg, s = src
    p = Period(date(2026, 9, 28), date(2026, 10, 11))
    k = compute(s, cfg, p).set_index("id")
    t = s["tickets"]
    closed = t[t.closed_at.dt.date.between(p.start, p.end)]
    assert k.loc["tickets_resolved", "current"] == len(closed)
    assert k.loc["sla_attainment", "current"] == pytest.approx((closed.resolution_hours <= closed.sla_hours).mean())
    tasks = s["tasks"]
    done = tasks[tasks.completed.between(p.start, p.end)]
    assert k.loc["on_time_delivery", "current"] == pytest.approx((done.completed <= done.due).mean())


def test_rag_respects_direction_and_bands():
    up = {"target": 0.9, "amber_band": 0.05, "direction": "higher_is_better"}
    down = {"target": 24, "amber_band": 6, "direction": "lower_is_better"}
    assert [rag(v, up) for v in (0.92, 0.87, 0.80)] == ["Green", "Amber", "Red"]
    assert [rag(v, down) for v in (20, 28, 40)] == ["Green", "Amber", "Red"]
    assert rag(5, {"target": None, "direction": "higher_is_better"}) == "—"
