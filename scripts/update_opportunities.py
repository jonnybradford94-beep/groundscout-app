#!/usr/bin/env python3
"""Update GroundScout tenders from the public Find a Tender OCDS feed."""
import datetime as dt
import json
import pathlib
import re
import urllib.parse
import urllib.request
import urllib.error

OUT = pathlib.Path("data/opportunities.json")
API = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
TODAY = dt.datetime.now(dt.timezone.utc)
KEYWORDS = re.compile(r"groundwork|civil engineering|excavat|drainage|ducting|kerbing|fenc|tree surg|arboricultur|vegetation|grass cut|landscap|forestry|woodland|telecom|fibre|fiber|cabling|haulage|skip|waste|demolition|site clearance|highway|road maintenance|construction|floodlight|plant hire|earthwork|reinstatement|scrub|mulch|chipp", re.I)
NI = re.compile(r"northern ireland|belfast|antrim|armagh|downpatrick|newry|mourne|county down|lisburn|derry|strabane|mid ulster|fermanagh|omagh|causeway|coleraine|newtownabbey|ards|banbridge|craigavon|lurgan|bangor|carrickfergus|ballymena|enniskillen|magherafelt|larne|newcastle|kilkeel|warrenpoint|castlewellan|dungannon", re.I)

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent":"GroundScout/1.0 (public procurement opportunity monitor)", "Accept":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP {}: {}".format(e.code, e.read(1000).decode("utf-8","replace"))) from e

def iso(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z","+00:00")).astimezone(dt.timezone.utc)
    except (ValueError, TypeError):
        return None

def as_text(v):
    if isinstance(v, str): return v
    if isinstance(v, dict): return " ".join(as_text(x) for x in v.values())
    if isinstance(v, list): return " ".join(as_text(x) for x in v)
    return ""

def extract(release):
    tender = release.get("tender") or {}
    if not isinstance(tender, dict): return None
    title = tender.get("title") or release.get("title") or ""
    desc = tender.get("description") or release.get("description") or ""
    buyer = (release.get("buyer") or {}).get("name","")
    parties = release.get("parties") or []
    locations = as_text(tender.get("deliveryAddresses") or tender.get("deliveryAddress") or tender.get("items") or "")
    area_text = " ".join([title,desc,buyer,locations])
    if not KEYWORDS.search(title+" "+desc): return None
    # Do not infer NI from generic wording such as "down" or "Newcastle" alone.
    ni_specific = re.search(r"northern ireland|belfast|county down|downpatrick|newry|mourne|castlewellan|kilkeel|warrenpoint|lisburn|county antrim|county armagh|derry and strabane|newtownabbey|ards and north down|fermanagh|omagh|mid ulster|causeway coast|banbridge|craigavon|ballyclare|ballymena|carrickfergus|enniskillen|dungannon", area_text, re.I)
    scotland = re.search(r"scotland|scottish|dundee|montrose|glasgow|edinburgh|aberdeen|inverness|perth and kinross|fife|stirling", " ".join([title,buyer,locations]), re.I)
    if not ni_specific or scotland: return None
    tags = release.get("tag") or []
    is_award = any("award" in str(tag).lower() for tag in tags)
    end = iso((tender.get("tenderPeriod") or {}).get("endDate"))
    if not is_award and (not end or end < TODAY - dt.timedelta(days=90)): return None
    if is_award:
        # Awards can be used as potential subcontracting leads, not advertised open tenders.
        if (TODAY - (iso(release.get("date")) or TODAY)).days > 90: return None
    rid = str(release.get("id") or "")
    match = re.search(r"(\d{6}-20\d{2})", rid)
    notice = match.group(1) if match else ""
    if not notice: return None
    # Use the buyer's council identity for council pins, never a passing mention in the description.
    council_names = {
        "Newry, Mourne and Down": r"newry.{0,20}mourne.{0,20}down",
        "Ards and North Down": r"ards.{0,15}north down",
        "Lisburn and Castlereagh": r"lisburn.{0,15}castlereagh",
        "Armagh, Banbridge and Craigavon": r"armagh.{0,20}banbridge.{0,20}craigavon",
        "Antrim and Newtownabbey": r"antrim.{0,15}newtownabbey",
        "Mid and East Antrim": r"mid.{0,10}east antrim",
        "Causeway Coast and Glens": r"causeway coast.{0,10}glens",
        "Derry City and Strabane": r"derry.{0,20}strabane",
        "Fermanagh and Omagh": r"fermanagh.{0,15}omagh",
        "Mid Ulster": r"mid ulster",
        "Belfast": r"belfast city council",
    }
    area = next((name for name, pattern in council_names.items() if re.search(pattern, buyer, re.I)), "Northern Ireland-wide")
    return dict(id=notice,title=title,description=as_text(desc)[:1800],category="award" if is_award else "tender",area=area,buyer=buyer,published=release.get("date"),deadline=end.isoformat() if end else None,url="https://www.find-tender.service.gov.uk/Notice/"+notice,source="Find a Tender",ocid=release.get("ocid",""))

def main():
    previous = json.loads(OUT.read_text()) if OUT.exists() else []
    start = (TODAY - dt.timedelta(days=180)).strftime("%Y-%m-%dT%H:%M:%S")
    found = {}
    errors = []
    for stage in ("tender","award"):
        cursor = None
        for _ in range(35):
            params = {"updatedFrom":start,"stages":stage,"limit":"100"}
            if cursor: params["cursor"] = cursor
            url = API+"?"+urllib.parse.urlencode(params)
            try:
                payload = get(url)
            except Exception as e:
                errors.append(str(e))
                break
            for release in payload.get("releases",[]):
                item = extract(release)
                if item: found[item["id"]] = item
            # Find a Tender requires the exact nextCursor, not a next link or altered cursor.
            cursor = payload.get("nextCursor")
            if not cursor: break
    if errors and not found:
        print("WARNING: Feed unavailable; preserving existing data: "+"; ".join(errors))
        return
    for old in previous:
        if not isinstance(old,dict) or not old.get("id"): continue
        if old.get("id") in found: continue
        if re.search(r"scotland|scottish|dundee|montrose|glasgow|edinburgh|aberdeen|inverness|fife", str(old.get("title",""))+" "+str(old.get("buyer","")), re.I): continue
        if old.get("category") == "tender":
            end = iso(old.get("deadline"))
            if not end or end < TODAY - dt.timedelta(days=90): continue
        elif old.get("category") == "award":
            published = iso(old.get("published"))
            if not published or (TODAY-published).days>90: continue
        else: continue
        found[old["id"]] = old
    rows = sorted(found.values(),key=lambda r:(r.get("category")!="tender",r.get("deadline") or "9999",r.get("title") or ""))
    if not rows and previous:
        raise RuntimeError("Collector returned no matching opportunities; preserving existing file")
    OUT.write_text(json.dumps(rows,indent=2,ensure_ascii=False)+"\n")
    print(f"Saved {len(rows)} opportunities ({sum(r['category']=='tender' and iso(r.get('deadline')) >= TODAY for r in rows)} open tenders, {sum(r['category']=='tender' and iso(r.get('deadline')) < TODAY for r in rows)} recently closed tenders)")

if __name__ == "__main__":
    main()
