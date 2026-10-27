#!/usr/bin/env python3
"""Write data/ncaa_members.csv: every NCAA school that sponsors women's basketball,
with its division, conference, and athletics site.

Reads the NCAA directory (web3.ncaa.org/directory), which is open JSON. fetch_data.py
uses the file to find D3 games against Division I and II teams on schedule pages:
first by the opponent link's site, then by the opponent's name. Rerun each fall,
because schools change divisions.
"""
import csv
import json
import re
import urllib.request
from pathlib import Path

URL = "https://web3.ncaa.org/directory/api/directory/memberList?type=12&sportCode=WBB"
OUT = Path(__file__).resolve().parent.parent / "data" / "ncaa_members.csv"


def domain(url):
    """'http://www.odusports.com/' -> 'odusports.com'."""
    host = re.sub(r"^https?://", "", (url or "").strip().lower()).split("/")[0]
    return re.sub(r"^www\.", "", host)


def main():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (Tonight in D3 WBB page builder)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        members = json.loads(r.read())
    rows = sorted(({"name": m["nameOfficial"].strip(), "division": m["division"], "conference": (m.get("conferenceName") or "").strip(),
                    "site": domain(m.get("athleticWebUrl"))} for m in members if m.get("deactive") == "N"), key=lambda r: r["name"])
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "division", "conference", "site"])
        w.writeheader()
        w.writerows(rows)
    counts = {d: sum(1 for r in rows if r["division"] == d) for d in (1, 2, 3)}
    print(f"wrote {OUT} ({len(rows)} schools: {counts[1]} Division I, {counts[2]} Division II, {counts[3]} Division III)")


if __name__ == "__main__":
    main()
