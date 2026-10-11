#!/usr/bin/env python3
"""Update GroundScout tenders from the public Find a Tender OCDS feed."""
import datetime as dt
import json
import pathlib
import re
import urllib.parse
import urllib.request

OUT = pathlib.Path("data/opportunities.json")
API = "https://www.find-tender.service.gov.uk/api/1.1/ocdsReleasePackages"
TODAY = dt.datetime.now(dt.timezone.utc)
KEYWORDS = re.compile(r"groundwork|civil engineering|excavat|drainage|ducting|kerbing|fenc|tree surg|arboricultur|vegetation|grass cut|landscap|forestry|woodland|telecom|fibre|fiber|cabling|haulage|skip|waste|demolition|site clearance|highway|road maintenance|construction|floodlight|plant hire|earthwork|reinstatement|scrub|mulch|chipp", re.I)
NI = re.compile(r"northern ireland|belfast|antrim|armagh|downpatrick|newry|mourne|county down|lisburn|derry|strabane|mid ulster|fermanagh|omagh|causeway|coleraine|newtownabbey|ards|banbridge|craigavon|lurgan|bangor|carrickfergus|ballymena|enniskillen|magherafelt|larne|newcastle|kilkeel|warrenpoint|castlewellan|dungannon", re.I)

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent":"GroundScout/1.0 (public procurement opportunity monitor)", "Accept":"application/json"})
    with urllib.request.urlopen(req, timeout=40) as response:
        return json.load(response)

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
    if not NI.search(area_text) or not KEYWORDS.search(title+" "+desc): return None
    tags = release.get("tag") or []
    is_award = any("award" in str(tag).lower() for tag in tags)
    end = iso((tender.get("tenderPeriod") or {}).get("endDate"))
    if not is_award and (not end or end <= TODAY): return None
    if is_award:
        # Awards can be used as potential subcontracting leads, not advertised open tenders.
        if (TODAY - (iso(release.get("date")) or TODAY)).days > 90: return None
    rid = str(release.get("id") or "")
    match = re.search(r"(\d{6}-20\d{2})", rid)
    notice = match.group(1) if match else ""
    if not notice: return None
    area = "Northern Ireland-wide"
    if re.search(r"newry|mourne|downpatrick|castlewellan|newcastle|kilkeel|warrenpoint|county down", area_text, re.I): area = "County Down"
    elif re.search(r"belfast", area_text, re.I): area = "Belfast"
    elif re.search(r"armagh|craigavon|lurgan|banbridge", area_text, re.I): area = "County Armagh"
    elif re.search(r"antrim|ballymena|larne|newtownabbey|ballyclare", area_text, re.I): area = "County Antrim"
    return dict(id=notice,title=title,description=as_text(desc)[:1800],category="award" if is_award else "tender",area=area,buyer=buyer,published=release.get("date"),deadline=end.isoformat() if end else None,url="https://www.find-tender.service.gov.uk/Notice/"+notice,source="Find a Tender",ocid=release.get("ocid",""))

def main():
    previous = json.loads(OUT.read_text()) if OUT.exists() else []
    start = (TODAY - dt.timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S")
    found = {}
    errors = []
    for stage in ("tender","award"):
        cursor = None
        for _ in range(12):
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
            nxt = payload.get("next") or payload.get("nextCursor")
            if isinstance(nxt,str) and nxt.startswith("http"):
                cursor = urllib.parse.parse_qs(urllib.parse.urlparse(nxt).query).get("cursor",[None])[0]
            elif isinstance(nxt,str): cursor=nxt
            else: cursor=None
            if not cursor: break
    if errors and not found:
        raise RuntimeError("Feed unavailable; preserving existing data: "+"; ".join(errors))
    for old in previous:
        if not isinstance(old,dict) or not old.get("id"): continue
        if old.get("id") in found: continue
        if old.get("category") == "tender":
            end = iso(old.get("deadline"))
            if not end or end <= TODAY: continue
        elif old.get("category") == "award":
            published = iso(old.get("published"))
            if not published or (TODAY-published).days>90: continue
        else: continue
        found[old["id"]] = old
    rows = sorted(found.values(),key=lambda r:(r.get("category")!="tender",r.get("deadline") or "9999",r.get("title") or ""))
    if not rows and previous:
        raise RuntimeError("Collector returned no matching opportunities; preserving existing file")
    OUT.write_text(json.dumps(rows,indent=2,ensure_ascii=False)+"\n")
    print(f"Saved {len(rows)} opportunities ({sum(r['category']=='tender' for r in rows)} open tenders)")

if __name__ == "__main__":
    main()
