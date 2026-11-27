#!/usr/bin/env python3
"""Write data/team_names.csv and data/rosters.csv. The script fetch_data.py uses them to tell whether a
live stats feed shows the game on the card. The page shows the class year from rosters.csv beside a box
line. Also write data/other_d3_names.csv with the names of Division III women's teams that play this
season but do not count. Provisional members such as Johnson & Wales Charlotte are on it. A schedule
row that names one is then not read as a counting team with a similar name.

Reads ~/projects/d3-bball-npi/myapp/data. `D3 Schools Name Mapping.csv` gives every way a source writes
a school's name, and 2027/players.csv gives this season's rosters. A host's crew can run one feed for
every game of its tournament. So a feed that names neither team and holds none of their players belongs
to another game. Rerun after a roster update or a name change.
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
    name = re.sub(r"\s*\(active[^)]*\)", "", (name or "").lstrip("#")).strip()
    return "" if name == "-" else name


def main():
    with open(NPI / f"{SEASON}/teams_mapping.txt", newline="", encoding="utf-8") as f:
        teams = {row[2].strip() for row in csv.reader(f) if len(row) >= 3}
    names, others = {}, {}
    with open(NPI / "D3 Schools Name Mapping.csv", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            seen = []
            for col in NAME_COLUMNS:
                n = clean(row.get(col))
                if n and n not in seen:
                    seen.append(n)
            if row["Display"] in teams:
                names[row["Display"]] = seen
            elif row["Display"] and row["Conference"].strip("- ") and row["Gender"] != "Men":
                # Keep a school with a conference and a women's team. Closed schools have "-" for
                # conference.
                others[row["Display"]] = seen
    for path, table in ((OUT / "team_names.csv", names), (OUT / "other_d3_names.csv", others)):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["team", "names"])
            for team in sorted(table):
                w.writerow([team, "|".join(table[team])])
    rosters = []
    with open(NPI / f"{SEASON}/players.csv", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["Team"].strip() in teams and row["Player"].strip():
                rosters.append((row["Team"].strip(), row["Player"].strip(), row.get("Class", "").strip()))
    with open(OUT / "rosters.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["team", "player", "class"])
        w.writerows(sorted(rosters))
    print(f"{len(names)} teams with names, {len(others)} other D3 teams, {len(rosters)} players -> {OUT}")


if __name__ == "__main__":
    main()
