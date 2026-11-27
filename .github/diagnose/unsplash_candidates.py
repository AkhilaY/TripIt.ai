"""Searches Unsplash for photo candidates for the places the app shows, so they can be picked by hand.

Prints one line per candidate: the search, the photo's id, size, likes, photographer and its image address.
Everything printed is public Unsplash information (no user data), since this repository's Actions logs are public.
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
PER = max(1, min(10, int(os.environ.get("PER") or 5)))
# Searches that find better photos than the place's caption does.
BETTER = {"The Grand Prix, Monaco": "Monaco harbour Monte Carlo", "The Pyramids and the Sphinx, Giza": "Giza pyramids",
          "Mount Fuji from Tokyo": "Tokyo Mount Fuji", "Overwater villas, Maldives": "Maldives overwater villas",
          "Westminster, London": "Big Ben Westminster London", "Canal houses, Amsterdam": "Amsterdam canal houses"}


def queries() -> list[str]:
    given = [q.strip() for q in (os.environ.get("QUERIES") or "").split(";") if q.strip()]
    if given:
        return given
    swift = open("ios/TripIt/Design/WorldScenes.swift", encoding="utf-8").read()
    places = re.findall(r'place: "([^"]+)"', swift)
    return [BETTER.get(p, p) for p in places] + ["Zurich old town", "Lucerne Chapel Bridge"]


def search(q: str) -> list[dict]:
    url = "https://api.unsplash.com/search/photos?" + urllib.parse.urlencode(
        {"query": q, "per_page": PER, "orientation": "portrait", "content_filter": "high"})
    req = urllib.request.Request(url, headers={"Authorization": f"Client-ID {KEY}", "Accept-Version": "v1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        left = r.headers.get("X-Ratelimit-Remaining")
        data = json.load(r)
    return data.get("results", []), left


def main() -> None:
    if not KEY:
        sys.exit("UNSPLASH_ACCESS_KEY isn't set")
    for i, q in enumerate(queries(), 1):
        try:
            results, left = search(q)
        except Exception as e:  # noqa: BLE001
            print(f"Q{i} | {q} | error {type(e).__name__}: {getattr(e, 'code', '')}", flush=True)
            continue
        for r in results:
            raw = r["urls"]["raw"].split("?")[0]
            if not raw.startswith("https://images.unsplash.com/"):
                continue  # Unsplash+ photos aren't free to use
            u = r["user"]
            print(f"Q{i} | {q} | {r['id']} | {r['width']}x{r['height']} | {r['likes']} | {u['name']} (@{u['username']}) | {raw}",
                  flush=True)
        print(f"Q{i} | {q} | {len(results)} found, {left} searches left this hour", flush=True)
        time.sleep(0.5)


if __name__ == "__main__":
    main()
