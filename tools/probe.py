"""Fetch each URL with the site's user agent and with a browser's, and print the status code and size.
Run it on a GitHub runner through the Probe URLs workflow to see what a host tells the runner:

    gh workflow run probe.yml -f urls="https://example.edu/a https://example.edu/b"
"""
import sys
import urllib.error
import urllib.request

AGENTS = {
    "site": "Mozilla/5.0 (tonightind3wbb.com page builder)",
    "browser": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
}


def fetch(url, agent):
    req = urllib.request.Request(url, headers={"User-Agent": agent, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return f"{resp.status} {len(resp.read())} bytes"
    except urllib.error.HTTPError as exc:
        return f"{exc.code} {exc.reason}"
    except (urllib.error.URLError, TimeoutError) as exc:
        return f"error {exc}"


for url in sys.argv[1:]:
    for name, agent in AGENTS.items():
        print(f"{name:8} {fetch(url, agent):24} {url}")
