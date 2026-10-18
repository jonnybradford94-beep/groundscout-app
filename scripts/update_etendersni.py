#!/usr/bin/env python3
"""Collect public eTendersNI notices, including every NMD Council category."""
import datetime as dt
import hashlib
import json
import pathlib
import re
import urllib.parse
import urllib.request
from bs4 import BeautifulSoup

OUT = pathlib.Path("data/opportunities.json")
BASE = "https://etendersni.gov.uk"
NMD = BASE + "/epps/notices/viewPublishedNotices.do?authorityId=3918&orgGroupId=4449"
HOME = BASE + "/epps/home.do?itemid=12"
NOW = dt.datetime.now(dt.timezone.utc)
CUTOFF = NOW - dt.timedelta(days=90)
MAINTENANCE = re.compile(r"maintenance|gritt|snow|tree|grass|ground|civil|drain|fenc|road|plant|woodland|forestry|waste|skip|haul|building|roof|repair|clean|landscap|construction|playground|demolition|surfacing|river|recycl|contractor|vegetation|estate|facility|facilities", re.I)
DATE = re.compile(r"\b(\d{2}/\d{2}/\d{4})(?:\s+\d{2}:\d{2}:\d{2})?\b")
NMD_NAME = re.compile(r"newry\s*[,/&-]?\s*mourne\s*(?:and|&)?\s*down", re.I)

def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; GroundScout/1.0)", "Accept": "text/html"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return BeautifulSoup(response.read(), "html.parser")

def published_date(text):
    dates = DATE.findall(text)
    if not dates:
        return None
    try:
        return dt.datetime.strptime(dates[-1], "%d/%m/%Y").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None

def record(title, published, url, buyer, area, kind, source):
    title = re.sub(r"\s+", " ", title).strip()
    if not title or not published or published < CUTOFF or published > NOW + dt.timedelta(days=1):
        return None
    key = hashlib.sha256((source + "|" + title.casefold() + "|" + published.strftime("%Y-%m-%d")).encode()).hexdigest()[:20]
    return dict(id="etni-auto-" + key, title=title, description="Published procurement notice. Closing date not independently verified; check the source before bidding.", category=kind, area=area, buyer=buyer, published=published.isoformat(), deadline=None, url=url, source=source)

def nmd_notices():
    found = []
    # Authority-specific public listing: every category of tender is eligible.
    for page in range(1, 6):
        url = NMD + "&d-446978-p=" + str(page) + "&d-446978-s=dateCreated&d-446978-o=2"
        soup = fetch(url)
        rows = soup.select("tr")
        if not rows and page == 1:
            raise RuntimeError("eTendersNI council listing did not contain a readable table")
        added = 0
        for tr in rows:
            cells = tr.find_all("td")
            if len(cells) < 5:
                continue
            text = tr.get_text(" ", strip=True)
            typ = cells[0].get_text(" ", strip=True)
            if not re.search(r"tender notice|contract notice|contract award|contract details", typ, re.I):
                continue
            title = cells[1].get_text(" ", strip=True)
            pub = published_date(cells[-1].get_text(" ", strip=True)) or published_date(text)
            if not pub or pub < CUTOFF:
                continue
            link = tr.find("a", href=True)
            href = urllib.parse.urljoin(BASE, link["href"]) if link else url
            kind = "award" if re.search(r"award|contract details", typ, re.I) else "tender"
            item = record(title, pub, href, "Newry, Mourne and Down District Council", "Newry, Mourne and Down", kind, "eTendersNI")
            if item:
                found.append(item)
                added += 1
        if page > 1 and not added:
            break
    return found

def home_notices():
    soup = fetch(HOME)
    found = []
    # Public notice board can include MultiQuote notices absent from the authority listing.
    for a in soup.find_all("a", href=True):
        parent = a.parent
        context = parent.get_text(" ", strip=True) if parent else ""
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 14:
            continue
        nmd = bool(NMD_NAME.search(title))
        if not nmd and not MAINTENANCE.search(title):
            continue
        match = re.search(r"\b(\d{2})\s+([A-Za-z]{3})\b", context[:45])
        if not match:
            continue
        try:
            published = dt.datetime.strptime(match.group(1) + " " + match.group(2) + " " + str(NOW.year), "%d %b %Y").replace(tzinfo=dt.timezone.utc)
            if published > NOW + dt.timedelta(days=1):
                published = published.replace(year=NOW.year-1)
        except ValueError:
            continue
        area = "Newry, Mourne and Down" if nmd else "Northern Ireland-wide"
        buyer = "Newry, Mourne and Down District Council" if nmd else ""
        item = record(title, published, urllib.parse.urljoin(BASE, a["href"]), buyer, area, "tender", "eTendersNI news")
        if item:
            found.append(item)
    return found

def main():
    previous = json.loads(OUT.read_text())
    if not isinstance(previous, list):
        raise RuntimeError("Existing opportunities file is not a list")
    council = nmd_notices()
    news = home_notices()
    incoming = council + news
    print(f"eTendersNI public listing parsed: {len(council)} council notices and {len(news)} news notices")
    if not incoming:
        raise RuntimeError("No recent notices could be parsed; keeping previous feed unchanged")
    existing = {x["id"]: x for x in previous if isinstance(x, dict) and x.get("id")}
    for item in incoming:
        existing[item["id"]] = item
    kept = []
    for item in existing.values():
        if str(item.get("id", "")).startswith("etni-auto-"):
            pub = item.get("published")
            try:
                when = dt.datetime.fromisoformat(pub.replace("Z", "+00:00"))
                if when < CUTOFF:
                    continue
            except (ValueError, AttributeError):
                continue
        kept.append(item)
    OUT.write_text(json.dumps(kept, indent=2, ensure_ascii=False) + "\n")
    print(f"GroundScout now has {len(kept)} opportunities")

if __name__ == "__main__":
    main()
