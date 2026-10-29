"""
Consolidate the three sources, validate them, and compute every KPI in config/kpis.yml
for a reporting period and the period before it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
SLA = {"P1": 4, "P2": 24, "P3": 72}


@dataclass
class Period:
    start: date
    end: date

    @property
    def label(self) -> str:
        return f"{self.start:%b %d} – {self.end:%b %d, %Y}"

    def previous(self) -> "Period":
        n = (self.end - self.start).days + 1
        return Period(self.start - timedelta(days=n), self.end - timedelta(days=n))


def load_config(path: Path = ROOT / "config" / "kpis.yml") -> dict:
    return yaml.safe_load(path.read_text())


def load_sources(cfg: dict, raw: Path = RAW) -> dict[str, pd.DataFrame]:
    """Read each source in its native shape and standardise columns, types and team names."""
    alias = cfg["reporting"]["team_aliases"]

    t = pd.read_csv(raw / "support_tickets.csv")
    t["opened_at"] = pd.to_datetime(t["opened_at"], format="%Y-%m-%d %H:%M")
    t["closed_at"] = pd.to_datetime(t["closed_at"], format="%Y-%m-%d %H:%M", errors="coerce")
    t["team"] = t["team"].map(alias).fillna(t["team"])
    t["sla_hours"] = t["priority"].map(SLA)
    t["resolution_hours"] = (t["closed_at"] - t["opened_at"]).dt.total_seconds() / 3600
    t["reopened"] = t["reopened"].eq("Y")

    raw_tracker = pd.read_excel(raw / "delivery_tracker.xlsx", header=None)
    header_row = raw_tracker.index[raw_tracker.iloc[:, 0].astype(str).eq("Task ID")][0]   # find the table
    k = pd.read_excel(raw / "delivery_tracker.xlsx", header=header_row)
    k = k.rename(columns={"Task ID": "task_id", "Owner": "owner", "Team": "team", "Start": "start", "Due": "due",
                          "Completed": "completed", "Est. Hours": "est_hours", "Rework?": "rework"})
    for c in ("start", "due", "completed"):
        k[c] = pd.to_datetime(k[c], format="%m/%d/%Y", errors="coerce").dt.date
    k["team"] = k["team"].map(alias).fillna(k["team"])
    k["rework"] = k["rework"].eq("Yes")

    s = pd.read_csv(raw / "timesheets.csv")
    s["work_date"] = pd.to_datetime(s["date"], format="%d-%b-%Y").dt.date
    s["team"] = s["team_name"].map(alias).fillna(s["team_name"])
    s = s.drop(columns=["date", "team_name"])
    return {"tickets": t, "tasks": k, "timesheets": s}


def validate(src: dict[str, pd.DataFrame], cfg: dict) -> pd.DataFrame:
    """Checks that run before any KPI is published. FAIL rows stop the report."""
    t, k, s = src["tickets"], src["tasks"], src["timesheets"]
    known = set(cfg["reporting"]["team_aliases"].values())
    checks = [
        ("Ticket IDs unique", t.ticket_id.is_unique, f"{t.ticket_id.duplicated().sum()} duplicates"),
        ("Task IDs unique", k.task_id.is_unique, f"{k.task_id.duplicated().sum()} duplicates"),
        ("Every ticket has a priority with an SLA", t.sla_hours.notna().all(), f"{t.sla_hours.isna().sum()} missing"),
        ("No ticket closed before it was opened", (t.resolution_hours.dropna() >= 0).all(),
         f"{(t.resolution_hours < 0).sum()} negative durations"),
        ("All team names map to a standard team", set(t.team) | set(k.team) | set(s.team) <= known,
         f"unmapped: {sorted((set(t.team) | set(k.team) | set(s.team)) - known)}"),
        ("Billable hours never exceed hours logged", (s.billable_hours <= s.hours_logged).all(),
         f"{(s.billable_hours > s.hours_logged).sum()} rows"),
        ("Task dates parse and due >= start", (k.due >= k.start).all(), f"{(k.due < k.start).sum()} rows"),
    ]
    return pd.DataFrame([{"check": c, "status": "PASS" if ok else "FAIL", "detail": "" if ok else d}
                         for c, ok, d in checks])


def compute(src: dict[str, pd.DataFrame], cfg: dict, period: Period) -> pd.DataFrame:
    con = duckdb.connect()
    for name, df in src.items():
        con.register(name, df)
    rows = []
    prev = period.previous()
    for k in cfg["kpis"]:
        def val(p: Period):
            sql = k["sql"].replace(":start", f"date '{p.start}'").replace(":end", f"date '{p.end}'")
            v = con.execute(sql).fetchall()[0][0]
            return None if v is None else float(v)
        cur, before = val(period), val(prev)
        rows.append({"team": k["team"], "kpi": k["name"], "id": k["id"], "current": cur, "previous": before,
                     "change": None if cur is None or before is None else cur - before,
                     "target": k.get("target"), "status": rag(cur, k), "format": k["format"],
                     "direction": k["direction"], "definition": k["definition"]})
    return pd.DataFrame(rows)


def rag(value, k) -> str:
    target = k.get("target")
    if target is None or value is None:
        return "—"
    gap = value - target if k["direction"] == "higher_is_better" else target - value
    if gap >= 0:
        return "Green"
    return "Amber" if -gap <= k.get("amber_band", 0) else "Red"


def trend(src: dict[str, pd.DataFrame], cfg: dict, end: date, n_periods: int = 8) -> pd.DataFrame:
    """KPI values for the last n periods, for trend charts."""
    days = cfg["reporting"]["period_days"]
    out = []
    for i in range(n_periods - 1, -1, -1):
        e = end - timedelta(days=days * i)
        p = Period(e - timedelta(days=days - 1), e)
        df = compute(src, cfg, p)[["id", "current"]]
        df["period_end"] = e
        out.append(df)
    return pd.concat(out).pivot(index="period_end", columns="id", values="current")
