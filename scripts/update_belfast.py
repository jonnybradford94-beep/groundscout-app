#!/usr/bin/env python3
"""Collect dated live works and maintenance notices from Belfast's official page."""
import datetime as dt
import json
import re
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

SOURCE = "https://www.belfastcity.gov.uk/business-and-investment/tenders/tender-opportunities"
OUT = Path("data/belfast.json")
RELEVANT = re.compile(r"works|construction|maintenan|repair|ground|tree|fenc|drain|waste|haul|skip|landscap|surfacing|court|excavat|demolition|gritt|snow|plant hire", re.I)

def parse(html, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    soup = BeautifulSoup(html, "html.parser")
    heading = next((h for h in soup.find_all(re.compile("^h[1-6]$"))
                    if h.get_text(" ", strip=True).casefold() == "current tendering opportunities"), None)
    if heading is None:
        raise RuntimeError("Current opportunities heading missing; preserving existing data")
    table = None
    for node in heading.next_elements:
        if getattr(node, "name", "") in ("h2", "h3"):
            break
        if getattr(node, "name", "") == "table":
            table = node
            break
    if table is None:
        raise RuntimeError("Current tender table missing; preserving existing data")
    headers = table.find("tr").get_text(" ", strip=True).lower()
    if "reference" not in headers or "closing" not in headers:
        raise RuntimeError("Unexpected current tender columns")
    records = []
    dated_rows = 0
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all("td")
        if len(cells) != 3:
            continue
        ref, title, closing = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)).strip() for c in cells]
        if re.search(r"pre.market|PME", ref + " " + title, re.I):
            continue
        match = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})", closing)
        if not match:
            continue  # Ongoing DPS applications are not dated work packages.
        dated_rows += 1
        if not RELEVANT.search(title):
            continue
        # Do not invent a time when the source omits it.
        if re.search(r"12\s*(?:noon|:00)|noon", closing, re.I):
            hour, minute = 12, 0
        else:
            time_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", closing, re.I)
            if not time_match:
                raise RuntimeError("Relevant deadline time missing: " + ref)
            hour = int(time_match[1]) % 12 + (12 if time_match[3].lower() == "pm" else 0)
            minute = int(time_match[2] or 0)
        day = dt.datetime.strptime(" ".join(match.groups()), "%d %B %Y")
        deadline = day.replace(hour=hour, minute=minute, tzinfo=ZoneInfo("Europe/London"))
        if deadline <= now:
            continue
        records.append(dict(
            id="bcc-" + re.sub(r"[^a-z0-9]+", "-", ref.lower()).strip("-"),
            reference=ref, title=title, category="tender", area="Belfast",
            buyer="Belfast City Council", deadline=deadline.isoformat(),
            url=SOURCE, source="Belfast City Council current tender list",
            checked_at=now.isoformat(),
            description=ref + ". Listed on Belfast City Council's current tender page. "
                        "Check eSourcing NI for documents, eligibility, site visits and updates. "
                        "Belfast pin is a council-area marker, not the work site."))
    if not dated_rows:
        raise RuntimeError("No dated tender rows parsed; preserving existing data")
    return records

def main():
    req = urllib.request.Request(SOURCE, headers={"User-Agent": "GroundScout/1.0", "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=45) as response:
        rows = parse(response.read())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(OUT)
    print("Saved", len(rows), "current Belfast works/maintenance notices")

if __name__ == "__main__":
    main()
