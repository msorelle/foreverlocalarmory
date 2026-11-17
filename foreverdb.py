"""Fetch catalog details from the authenticated ForeverDB API."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


QUALITIES = ("Poor", "Common", "Uncommon", "Rare", "Epic", "Legendary")


def label(value):
    if isinstance(value, dict):
        return label(value.get("name") or value.get("label") or value.get("description"))
    return value.strip() if isinstance(value, str) else None


def tooltip_lines(value):
    if isinstance(value, list):
        for entry in value:
            yield from tooltip_lines(entry)
    elif isinstance(value, dict):
        text = label(value)
        amount = value.get("value", value.get("amount"))
        if text and type(amount) in (int, float):
            yield f"{amount:+g} {text}"
        elif text:
            yield text
        elif type(value.get("min")) in (int, float) and type(value.get("max")) in (int, float):
            yield f"{value['min']}–{value['max']}"
        else:
            for key, entry in value.items():
                if type(entry) in (int, float):
                    yield f"{entry:+g} {key}"
    elif label(value):
        yield label(value)


def item_details(item):
    quality = item.get("quality")
    if type(quality) is int and 0 <= quality < len(QUALITIES):
        quality = QUALITIES[quality]
    tooltip = []
    for names, heading in (
        (("itemLevel",), "Item level"),
        (("requiredLevel",), "Requires level"),
        (("binding", "bind"), ""),
        (("damage",), "Damage"),
        (("speed",), "Speed"),
        (("armor",), "Armor"),
        (("stats",), ""),
        (("effects",), ""),
        (("speculationReasons",), ""),
        (("dataFromBuild",), "Details from build"),
    ):
        value = next((item[name] for name in names if item.get(name) is not None), None)
        lines = [str(value)] if type(value) in (int, float) else tooltip_lines(value)
        tooltip.extend(f"{heading} {line}" if heading else line for line in lines)
    if item.get("betaEvent") is True:
        tooltip.append("Historical beta event item")
    if item.get("speculation") is True:
        tooltip.append("Availability uncertain")

    icon = item.get("iconUrl") or item.get("icon")
    if not isinstance(icon, str) or not icon.startswith("https://") or not urlsplit(icon).hostname:
        icon = None
    sell_price = item.get("sellPrice")
    return {
        "fromForeverDB": True,
        "name": label(item.get("name")),
        "description": label(item.get("description")),
        "quality": label(quality),
        "type": label(item.get("subclassName") or item.get("subclass")) or label(item.get("class")),
        "slot": label(item.get("slotName") or item.get("slot")),
        "icon": icon,
        "sellPrice": sell_price if type(sell_price) is int else None,
        "tooltip": list(dict.fromkeys(tooltip)),
    }


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the API key to a redirect destination.
        return None


def retry_delay(value):
    try:
        return max(1, int(value))
    except ValueError:
        try:
            return max(1, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError):
            return 60


class ForeverDB:
    def __init__(self, key):
        self.key = key
        self.opener = build_opener(NoRedirect())
        self.cache = {}
        self.retry_at = 0

    def item(self, item_id):
        if not self.key:
            return {"status": "Start the browser with a ForeverDB API key to see catalog details."}
        cached = self.cache.get(item_id)
        if cached and time.monotonic() < cached[0]:
            return cached[1]
        if time.monotonic() < self.retry_at:
            return {"status": "ForeverDB rate limit reached. Try again in a moment."}
        request = Request(f"https://foreverdb.net/api/v1/items/{item_id}", headers={
            "X-API-Key": self.key,
            "User-Agent": "ForeverLocalArmory/1.0 (local inventory browser)",
            "Accept": "application/json",
        })
        try:
            with self.opener.open(request, timeout=8) as response:
                payload = json.load(response)
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                raise ValueError("Expected a ForeverDB item object.")
            result = item_details(data)
        except HTTPError as error:
            with error:
                if error.code == 404:
                    result = {"status": "This item is unavailable in the ForeverDB catalog."}
                elif error.code == 429:
                    self.retry_at = time.monotonic() + retry_delay(error.headers.get("Retry-After", "60"))
                    return {"status": "ForeverDB rate limit reached. Try again in a moment."}
                elif error.code in (401, 403):
                    return {"status": "ForeverDB denied access. Check your approved API key."}
                elif error.code == 402:
                    return {"status": "ForeverDB requires a subscription for additional requests."}
                else:
                    raise
        self.cache[item_id] = time.monotonic() + 3600, result
        return result
