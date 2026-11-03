#!/usr/bin/env python3
"""Write docs/logos/<slug>.webp for every team in ~/projects/d3-bball-npi's logo_thumbs.json.

Each file is a 64 by 64 WebP. The page loads a logo only when its row scrolls into view.
GitHub Actions cannot read that repo, so the files are committed. Rerun this script by
hand when a school changes its logo or a team joins.
"""
import base64
import json
import re
from pathlib import Path

SOURCE = Path.home() / "projects" / "d3-bball-npi" / "myapp" / "data" / "logo_thumbs.json"
OUT = Path(__file__).resolve().parent.parent / "docs" / "logos"
PREFIX = "data:image/webp;base64,"


def slug(name):
    """The file name for a team. logoSlug() in build_site.LIVE_JS must match this."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    written = 0
    for team, entry in json.loads(SOURCE.read_text()).items():
        thumb = entry.get("thumb", "")
        if thumb.startswith(PREFIX):
            (OUT / f"{slug(team)}.webp").write_bytes(base64.b64decode(thumb[len(PREFIX):]))
            written += 1
    print(f"wrote {written} logos to {OUT}")


if __name__ == "__main__":
    main()
