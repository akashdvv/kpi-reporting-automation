"""
Build the biweekly KPI report.

    python data/generate.py                          # once: create the three raw sources
    python build_report.py                           # latest complete period (ends 2026-10-11)
    python build_report.py --period-end 2026-09-27   # any other period

Writes reports/kpi_report_<period-end>.xlsx and reports/kpi_summary_<period-end>.md.
Stops with exit code 1 (and no report) if a data check fails.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from kpi.excel_report import write
from kpi.pipeline import ROOT, Period, compute, load_config, load_sources, trend, validate

BLUE, ORANGE, INK_2, GRID = "#2a78d6", "#eb6834", "#52514e", "#e4e3df"


def fmt(v, f):
    if v is None or v != v:
        return "—"
    return {"int": f"{v:,.0f}", "pct": f"{v:.1%}", "dec1": f"{v:.1f}"}[f]


def markdown(period, kpis) -> str:
    lines = [f"# Biweekly performance report: {period.label}", ""]
    for team in ["Support", "Delivery"]:
        lines += [f"## {team}", "", "| KPI | This period | Last period | Target | Status |", "|---|---|---|---|---|"]
        for k in kpis[kpis.team == team].itertuples():
            lines.append(f"| {k.kpi} | {fmt(k.current, k.format)} | {fmt(k.previous, k.format)} | "
                         f"{fmt(k.target, k.format)} | {k.status} |")
        lines.append("")
    return "\n".join(lines)


def chart(tr) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
    for ax, (kid, title, target, color) in zip(axes, [("sla_attainment", "Support: SLA attainment", 0.90, BLUE),
                                                       ("on_time_delivery", "Delivery: on-time delivery", 0.85, ORANGE)]):
        ax.plot(tr.index, tr[kid] * 100, marker="o", color=color, linewidth=2)
        ax.axhline(target * 100, color=INK_2, linestyle="--", linewidth=0.9)
        ax.text(tr.index[0], target * 100 + 1.5, f"target {target:.0%}", fontsize=9, color=INK_2)
        ax.set_title(title, loc="left", fontweight="bold")
        ax.set_ylabel("%")
        ax.set_ylim(0, 100)
        ax.tick_params(axis="x", rotation=45)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.yaxis.grid(True, color=GRID)
    fig.tight_layout()
    (ROOT / "images").mkdir(exist_ok=True)
    fig.savefig(ROOT / "images" / "kpi_trends.png", dpi=150)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period-end", default="2026-10-11")
    args = ap.parse_args()
    cfg = load_config()
    end = date.fromisoformat(args.period_end)
    period = Period(end - timedelta(days=cfg["reporting"]["period_days"] - 1), end)

    src = load_sources(cfg)
    checks = validate(src, cfg)
    if (checks.status == "FAIL").any():
        print(checks.to_string(index=False))
        print("Data checks failed - report not produced.")
        return 1

    kpis = compute(src, cfg, period)
    tr = trend(src, cfg, end, n_periods=7)
    (ROOT / "reports").mkdir(exist_ok=True)
    write(ROOT / "reports" / f"kpi_report_{end}.xlsx", period, kpis, tr, checks, cfg)
    md = markdown(period, kpis)
    (ROOT / "reports" / f"kpi_summary_{end}.md").write_text(md)
    chart(tr)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
