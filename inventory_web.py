"""Serve a private, read-only WoW Forever inventory browser."""

import argparse
from collections import Counter
from datetime import datetime
from getpass import getpass
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import sys
from urllib.error import URLError
from urllib.parse import urlsplit
import webbrowser

from foreverdb import ForeverDB
from syndicator import read_characters


LOCATIONS = {
    "bags": "Bags", "bank": "Bank", "bankTabs": "Bank", "equipped": "Equipped",
    "mail": "Mail", "auctions": "Auctions", "void": "Void storage",
}
ITEM_NAME = re.compile(r"\|h\[(.*?)\]\|h")
ITEM_QUALITIES = ("Poor", "Common", "Uncommon", "Rare", "Epic", "Legendary", "Artifact", "Heirloom")


def stacks(node):
    if node.kind != "table":
        return
    entries = node.entries
    item = entries.get(("string", "itemID"))
    if item and item.kind == "number" and item.value > 0:
        link = entries.get(("string", "itemLink"))
        name = ITEM_NAME.search(link.value) if link and link.kind == "string" else None
        count = entries.get(("string", "itemCount"))
        item_id = int(item.value)
        label = name[1].encode("latin-1").decode("utf-8", errors="replace") if name else f"Item {item_id}"
        quality = entries.get(("string", "quality"))
        rarity = None
        if quality and quality.kind == "number" and quality.value in range(len(ITEM_QUALITIES)):
            rarity = ITEM_QUALITIES[int(quality.value)]
        yield item_id, label, rarity, int(count.value) if count and count.kind == "number" else 1
        return
    for child in entries.values():
        yield from stacks(child)


def inventory(game_dir, ownership):
    characters = []
    rows = []
    for account, names in ownership.items():
        path = game_dir / "WTF" / "Account" / account / "SavedVariables" / "Syndicator.lua"
        with path.open("rb") as source:
            modified = os.fstat(source.fileno()).st_mtime
            saved_characters = read_characters(source.read())
        saved_at = datetime.fromtimestamp(modified).astimezone().isoformat()
        for name in names:
            character = saved_characters["string", name]
            characters.append({"name": name, "savedAt": saved_at})
            for section, location in LOCATIONS.items():
                container = character.table().get(("string", section))
                if container is None:
                    continue
                counts = Counter()
                rarities = {}
                for item_id, label, rarity, count in stacks(container):
                    key = item_id, label
                    counts[key] += count
                    if rarity:
                        rarities[key] = rarity
                rows.extend({"id": item_id, "name": label, "count": count,
                             "rarity": rarities.get((item_id, label)),
                             "character": name, "location": location}
                            for (item_id, label), count in counts.items())
    rows.sort(key=lambda row: (row["name"].casefold(), row["character"], row["location"]))
    return {"characters": characters, "items": rows}


def serve(catalog, game_dir, ownership):
    page = Path(__file__).with_name("inventory.html").read_bytes()
    prefix = "/" + secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, value, status=200):
            html = isinstance(value, bytes)
            body = value if html else json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src https:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                self.send({"error": "Invalid host."}, 400)
                return
            url = urlsplit(self.path)
            path = url.path
            if path == f"{prefix}/":
                self.send(page)
            elif path == f"{prefix}/inventory":
                try:
                    result = inventory(game_dir, ownership)
                except (OSError, ValueError, KeyError):
                    self.send({"error": "Could not read the configured Syndicator saves. Check the game folder and ownership file, then try again after logging out."}, 503)
                else:
                    self.send(result)
            elif match := re.fullmatch(f"{prefix}/item/([0-9]{{1,10}})", path):
                try:
                    result = catalog.item(int(match[1]))
                except (URLError, TimeoutError, ValueError):
                    self.send({"error": "ForeverDB is temporarily unavailable."}, 502)
                else:
                    self.send(result)
            else:
                self.send({"error": "Page not found."}, 404)

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        url = f"http://127.0.0.1:{server.server_port}{prefix}/"
        print(f"Open {url}\nPress Ctrl+C to stop.", flush=True)
        webbrowser.open(url)
        server.serve_forever()


def read_ownership(path):
    ownership = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(ownership, dict) or not ownership or any(
        not re.fullmatch(r"[a-zA-Z0-9_#-]+", account)
        or not isinstance(names, list)
        or not names
        or any(not isinstance(name, str) or not name.strip() for name in names)
        for account, names in ownership.items()
    ):
        raise ValueError("Ownership must map Syndicator account folders to lists of character keys.")
    names = [name for group in ownership.values() for name in group]
    if len(names) != len(set(names)):
        raise ValueError("Assign each character to one account in the ownership file.")
    return ownership


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", type=Path, required=True, help="Path to the WoW _forever_ folder")
    parser.add_argument("--ownership", type=Path, required=True, help="Account-to-character ownership JSON")
    parser.add_argument("--offline", action="store_true", help="Browse saves without ForeverDB lookups")
    args = parser.parse_args()
    try:
        ownership = read_ownership(args.ownership)
        if not (args.game_dir / "WTF" / "Account").is_dir():
            raise ValueError("The game folder must contain WTF/Account.")
        key = ""
        if not args.offline:
            key = os.environ.get("FOREVERDB_API_KEY", "").strip()
            if not key and sys.stdin.isatty():
                key = getpass("ForeverDB API key (Enter to browse offline): ").strip()
        serve(ForeverDB(key), args.game_dir, ownership)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
