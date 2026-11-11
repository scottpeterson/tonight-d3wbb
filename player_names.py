"""Map a box score line to the roster player it belongs to.

The roster name is canonical. A box score or play-by-play spelling that differs maps to it ("Judith Vila Marti"
is "Judith Vila", "Jean Sierra" is "Sierra Jean", "B. BATCHELOR" is "Brooke Batchelor"), and a name the roster
lacks stands as written until the roster lists it. fetch_data.py and build_site.py share this module.
"""
import re


def norm(name):
    """Letters only, lowercase: "O'Brien" -> "obrien"."""
    return re.sub(r"[^a-z]", "", str(name or "").lower())


def words(name):
    """The letters of each word, lowercase: "Mj van der Horst" -> ["mj", "van", "der", "horst"]."""
    return [w for w in (norm(w) for w in str(name or "").split()) if w]


def line_words(line):
    """A box line's name words when the feed gives a first name: from first and last, 'Last, First', or
    'First Last'. [] when it gives an initial ('F. Last'), which match_player handles by initial and last name."""
    if line.get("first") and line.get("last"):
        return words(f'{line["first"]} {line["last"]}')
    abbr = str(line.get("abbr") or "")
    if "," in abbr:
        last, first = abbr.split(",", 1)
        found = words(first) + words(last)
        return found if len(found[0]) > 1 else []
    found = words(abbr)
    return found if found and len(found[0]) > 1 else []


def match_player(line, roster):
    """The roster player a box line belongs to, or None. In order: the same full name; the same words in another
    order; one name's words inside the other's (both at least two words); the first initial plus the last name.
    Each step counts only when exactly one roster player fits."""
    found = line_words(line)
    if found:
        full = "".join(found)
        hit = [p for p in roster if norm(p["name"]) == full]
        if hit:
            return hit[0]
        key = sorted(found)
        hit = [p for p in roster if sorted(words(p["name"])) == key]
        if len(hit) == 1:
            return hit[0]
        if len(found) >= 2:
            mine = set(found)
            hit = [p for p in roster if len(theirs := set(words(p["name"]))) >= 2 and (theirs <= mine or mine <= theirs)]
            if len(hit) == 1:
                return hit[0]
    abbr = str(line.get("abbr") or "")
    m = re.match(r"\s*([A-Za-z])[a-z]*\.?\s+(.+)$", abbr) or re.match(r"\s*(.+?),\s*([A-Za-z])", abbr)
    if not m:
        return None
    initial, last = (m.group(1), m.group(2)) if "," not in abbr else (m.group(2), m.group(1))
    last_n = norm(last)
    hit = [p for p in roster if norm(p["name"].split(" ")[-1]) == last_n and norm(p["name"])[:1] == initial.lower()]
    return hit[0] if len(hit) == 1 else None


def name_line(name):
    """A box-line shaped dict for a stored name string, so match_player can place it: 'F. Last' keeps the
    initial path, anything else splits into first and last."""
    parts = str(name or "").split()
    if len(parts) >= 2 and len(norm(parts[0])) > 1:
        return {"first": parts[0], "last": " ".join(parts[1:]), "abbr": name}
    return {"first": "", "last": "", "abbr": name}
