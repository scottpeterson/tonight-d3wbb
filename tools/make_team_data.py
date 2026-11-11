#!/usr/bin/env python3
"""Write data/team_names.csv and data/rosters.csv, the lists fetch_data.py uses to tell whether a live
stats feed shows the game on the card, and the class year the page shows beside a box line.

Reads ~/projects/d3-bball-npi/myapp/data: `D3 Schools Name Mapping.csv` for every way a source writes a
school's name, and 2027/players.csv for this season's rosters. A host's crew can run one feed for every
game of its tournament, so a feed that names neither team, and holds none of their players, belongs to
another game. Rerun after a roster update or a name change.
"""
import csv
import re
from pathlib import Path

NPI = Path.home() / "projects" / "d3-bball-npi" / "myapp" / "data"
OUT = Path(__file__).resolve().parent.parent / "data"
SEASON = "2027"
NAME_COLUMNS = ("Display", "Massey", "d3hoops", "stats.NCAA.org", "NCAA Championship Manual", "Former Display")


def clean(name):
    """'#Pratt Institute (active 2022-23)' -> 'Pratt Institute'."""
    return re.sub(r"\s*\(active[^)]*\)", "", (name or "").lstrip("#")).strip()


def main():
    with open(NPI / f"{SEASON}/teams_mapping.txt", newline="", encoding="utf-8") as f:
        teams = {row[2].strip() for row in csv.reader(f) if len(row) >= 3}
    names = {}
    with open(NPI / "D3 Schools Name Mapping.csv", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["Display"] in teams:
                seen = []
                for col in NAME_COLUMNS:
                    n = clean(row.get(col))
                    if n and n not in seen:
                        seen.append(n)
                names[row["Display"]] = seen
    with open(OUT / "team_names.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["team", "names"])
        for team in sorted(names):
            w.writerow([team, "|".join(names[team])])
    rosters = []
    with open(NPI / f"{SEASON}/players.csv", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["Team"].strip() in teams and row["Player"].strip():
                rosters.append((row["Team"].strip(), row["Player"].strip(), row.get("Class", "").strip()))
    with open(OUT / "rosters.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["team", "player", "class"])
        w.writerows(sorted(rosters))
    print(f"{len(names)} teams with names, {len(rosters)} players -> {OUT}")


if __name__ == "__main__":
    main()
