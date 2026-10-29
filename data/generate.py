"""
Generate 16 weeks of operational data for two teams, as three differently-shaped sources:

  data/raw/support_tickets.csv      ticketing system export (Support team)
  data/raw/delivery_tracker.xlsx    project tracker workbook kept by the Delivery team
  data/raw/timesheets.csv           hours logged by every employee (both teams)

The sources disagree on formats in the ways real ones do: team names are spelled differently,
dates come in different formats, and the tracker has a header block above the table.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent / "raw"
SEED = 3
START = datetime(2026, 7, 6)          # Monday
WEEKS = 16
SUPPORT_STAFF = [f"S{i:02d}" for i in range(1, 9)]
DELIVERY_STAFF = [f"D{i:02d}" for i in range(1, 7)]
SLA_HOURS = {"P1": 4, "P2": 24, "P3": 72}


def main(out: Path = ROOT) -> None:
    rng = random.Random(SEED)
    out.mkdir(parents=True, exist_ok=True)

    # ---- Support tickets ----
    tickets, tid = [], 1
    for day in range(WEEKS * 7):
        d = START + timedelta(days=day)
        if d.weekday() >= 5:
            continue
        week = day // 7
        volume = int(rng.gauss(38 + 0.6 * week, 6))          # demand creeping up
        for _ in range(max(volume, 10)):
            pri = rng.choices(["P1", "P2", "P3"], [0.08, 0.37, 0.55])[0]
            opened = d + timedelta(hours=rng.uniform(8, 18))
            # staffing dip in weeks 10-11 slows resolution
            slow = 1.6 if week in (10, 11) else 1.0
            hours = rng.lognormvariate({"P1": 0.9, "P2": 2.4, "P3": 3.3}[pri], 0.7) * slow
            closed = opened + timedelta(hours=hours) if rng.random() > 0.03 else None
            tickets.append({
                "ticket_id": f"TCK-{tid:06d}", "opened_at": opened.strftime("%Y-%m-%d %H:%M"),
                "closed_at": closed.strftime("%Y-%m-%d %H:%M") if closed else "",
                "priority": pri, "assignee": rng.choice(SUPPORT_STAFF), "team": "Customer Support",
                "contacts_to_resolve": 1 if rng.random() < 0.71 - 0.08 * (slow > 1) else rng.randint(2, 4),
                "reopened": "Y" if rng.random() < 0.06 else "N"})
            tid += 1
    pd.DataFrame(tickets).to_csv(out / "support_tickets.csv", index=False)

    # ---- Delivery tracker (Excel, with a header block above the table) ----
    tasks = []
    for i in range(1, 241):
        start = START + timedelta(days=rng.randint(0, WEEKS * 7 - 21))
        planned = rng.choice([3, 5, 5, 8, 10, 13])
        due = start + timedelta(days=planned)
        slip = max(0, rng.gauss(0.5 if start < START + timedelta(weeks=9) else 2.2, 2.5))
        done = start + timedelta(days=planned + slip) if start + timedelta(days=planned + slip) < START + timedelta(weeks=WEEKS) else None
        tasks.append({"Task ID": f"DLV-{i:04d}", "Owner": rng.choice(DELIVERY_STAFF), "Team": "delivery",
                      "Start": start.strftime("%m/%d/%Y"), "Due": due.strftime("%m/%d/%Y"),
                      "Completed": done.strftime("%m/%d/%Y") if done else None,
                      "Est. Hours": planned * 6, "Rework?": "Yes" if rng.random() < 0.09 else "No"})
    df = pd.DataFrame(tasks)
    with pd.ExcelWriter(out / "delivery_tracker.xlsx", engine="openpyxl") as xw:
        pd.DataFrame({"A": ["Delivery Team - Project Tracker", "Maintained by: Delivery Lead", ""]}).to_excel(
            xw, sheet_name="Tracker", index=False, header=False)
        df.to_excel(xw, sheet_name="Tracker", index=False, startrow=3)

    # ---- Timesheets (both teams; team names spelled differently again) ----
    rows = []
    for day in range(WEEKS * 7):
        d = START + timedelta(days=day)
        if d.weekday() >= 5:
            continue
        for emp in SUPPORT_STAFF + DELIVERY_STAFF:
            if rng.random() < 0.05:
                continue                      # leave
            team = "CS" if emp.startswith("S") else "Delivery Team"
            total = 8.0
            productive = round(total * rng.uniform(0.70, 0.88), 1)
            rows.append({"date": d.strftime("%d-%b-%Y"), "employee_id": emp, "team_name": team,
                         "hours_logged": total, "billable_hours": productive})
    pd.DataFrame(rows).to_csv(out / "timesheets.csv", index=False)
    print(f"tickets {len(tickets)} | tasks {len(tasks)} | timesheet rows {len(rows)}")


if __name__ == "__main__":
    main()
