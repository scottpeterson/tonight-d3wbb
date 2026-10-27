#!/usr/bin/env python3
"""Write data/schools.csv: each school's schedule page, page type, and local time zone.

Reads ~/projects/d3-bball-npi (team_base_websites.csv for pages, school_demographics.csv
for state and longitude, 2027/teams_mapping.txt for the teams that count this season).
Rerun when a school changes its site or a team joins.
Schedule pages print tipoff in local time, often with no zone label, so fetch_data.py
needs each school's zone.
"""
import csv
from pathlib import Path

NPI = Path.home() / "projects" / "d3-bball-npi" / "myapp" / "data"
OUT = Path(__file__).resolve().parent.parent / "data" / "schools.csv"

EASTERN = {"CT", "DC", "DE", "GA", "IN", "MA", "MD", "ME", "MI", "NC", "NH", "NJ", "NY", "OH", "PA", "RI", "SC", "VA", "VT", "WV"}
CENTRAL = {"AL", "AR", "IA", "IL", "LA", "MN", "MO", "MS", "OK", "TX", "WI", "KS", "NE", "ND", "SD"}
MOUNTAIN = {"CO", "MT", "NM", "UT", "WY", "ID"}
PACIFIC = {"CA", "OR", "WA", "NV"}
# States split between Eastern and Central: the line runs near these longitudes at the D3 campuses.
SPLIT = {"TN": -85.0, "KY": -86.0, "FL": -85.0}
SEASON = "2027"


def zone(state, lon):
    if state in SPLIT:
        return "America/New_York" if lon > SPLIT[state] else "America/Chicago"
    if state == "AZ":
        return "America/Phoenix"
    if state == "HI":
        return "Pacific/Honolulu"
    if state == "AK":
        return "America/Anchorage"
    for states, tz in ((EASTERN, "America/New_York"), (CENTRAL, "America/Chicago"), (MOUNTAIN, "America/Denver"), (PACIFIC, "America/Los_Angeles")):
        if state in states:
            return tz
    raise ValueError(f"no zone for state {state}")


def main():
    with open(NPI / "school_demographics.csv", encoding="utf-8-sig") as f:
        where = {r["Team"]: r for r in csv.DictReader(f)}
    with open(NPI / "team_base_websites.csv", encoding="utf-8-sig") as f:
        sites = [r for r in csv.DictReader(f) if r.get("Team")]
    with open(NPI / SEASON / "teams_mapping.txt", encoding="utf-8-sig") as f:
        teams = {r["team_name"] for r in csv.DictReader(f)}
    sites = [s for s in sites if s["Team"] in teams]
    missing = [s["Team"] for s in sites if s["Team"] not in where]
    if missing:
        raise SystemExit(f"no location for: {', '.join(missing)}")
    OUT.parent.mkdir(exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["team", "type", "schedule", "tz"])
        for s in sorted(sites, key=lambda s: s["Team"]):
            loc = where[s["Team"]]
            w.writerow([s["Team"], s["Type"], s["Schedule"], zone(loc["State"], float(loc["Longitude"]))])
    print(f"wrote {OUT} ({len(sites)} schools)")


if __name__ == "__main__":
    main()
