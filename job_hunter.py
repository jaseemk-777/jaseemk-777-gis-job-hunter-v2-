"""GIS Job Hunter V2: broad legitimate discovery, ranking and private review reports.

Run with python job_hunter.py. Standard library only; no portal automation or employer outreach.
Reads GitHub repository secrets via environment. Reports aren't assertions of active vacancies.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from html import unescape
from html.parser import HTMLParser
import hashlib
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor, as_completed

import watcher  # Version 1: verified company Greenhouse/Lever/Ashby boards + Gmail-alert reader

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "settings.json"
BOARDS = ROOT / "boards.json"
STATE = ROOT / "data" / "seen.json"
HISTORY = ROOT / "data" / "jobs_history.csv"
LEGACY = ROOT / "data" / "Original_95_Job_Leads.csv"
REPORTS = ROOT / "reports"
NOW = datetime.now(timezone.utc)

INDIA_TERMS = ("india", "indian", "bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "delhi", "noida", "gurugram", "gurgaon", "chennai", "kochi", "kerala", "ahmedabad", "kolkata", "thiruvananthapuram", "visakhapatnam", "tirupati", "jaipur", "indore", "lucknow")
MIDDLE_EAST_TERMS = ("united arab emirates", " uae", "dubai", "abu dhabi", "sharjah", "saudi", "riyadh", "jeddah", "dammam", "qatar", "doha", "oman", "muscat", "bahrain", "kuwait", "jordan", "amman")
EUROPE_TERMS = ("europe", "germany", "berlin", "france", "paris", "netherlands", "amsterdam", "belgium", "spain", "madrid", "portugal", "lisbon", "italy", "milan", "ireland", "dublin", "poland", "warsaw", "sweden", "stockholm", "norway", "denmark", "finland", "austria", "switzerland", "swiss", "uk ", "united kingdom", "london", "england", "scotland", "czech", "prague", "romania", "hungary", "greece", "estonia", "latvia", "lithuania", "slovenia", "croatia")
INELIGIBLE_REMOTE = ("us only", "usa only", "u.s. only", "united states only", "north america only", "uk only", "eu only", "europe only", "european union only", "canada only", "residents of usa", "based in the us")
SENIOR_TITLES = ("senior", "lead ", "principal", "director", "head of", "vp ", "manager", "staff ", "architect", "chief ")
TITLE_POSITIVE = ("gis", "geospatial", "geography", "spatial", "remote sensing", "earth observation", "satellite", "cartograph", "geoinformat", "geodatabase", "mapping", "climate", "disaster", "environmental", "ecology", "geographic", "data analyst", "python developer", "urban plan")
GOOD_DETAILS = ("gis", "geospatial", "qgis", "arcgis", "earth engine", "remote sensing", "geographic information", "spatial analysis", "satellite imagery", "geopandas", "postgis", "spatial data", "climate risk")
SKILL_TERMS = {"qgis": 4, "arcgis": 4, "google earth engine": 5, "geospatial": 4, "remote sensing": 4, "satellite": 3, "python": 2, "sql": 2, "postgis": 3, "flood": 2, "climate": 2, "disaster": 2, "geojson": 2, "mapping": 1}
CSV_FIELDS = ["job_key", "company", "title", "region", "location", "work_mode", "india_remote_eligibility", "fit_score", "experience_flag", "posted_at", "freshness", "salary", "source", "url", "discovered_at", "notes"]


def textify(value):
    """Clean untrusted text for CSV/email. Don't let a feed write CSV formulas."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    out = watcher.plain(str(value)) if "<" in str(value) or "&" in str(value) else str(value)
    out = re.sub(r"\s+", " ", unescape(out)).strip()
    return out[:8000]


def safe_csv(value):
    s = textify(value)
    return "'" + s if s.startswith(("=", "+", "-", "@", "\t")) else s


def make_url(url):
    return watcher.canonical_url(url)


def date_parser(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        val = float(value)
        if val > 1e11: val /= 1000
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    if s.isdigit():
        return date_parser(int(s))
    try:
        date = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date.astimezone(timezone.utc)
    except ValueError:
        return None


def get_json(url, headers=None):
    # URLs are assembled from fixed provider endpoints only, never followed from a job listing.
    request = Request(url, headers={"User-Agent": "PersonalGISJobHunter/2.0 (job discovery)", "Accept": "application/json", **(headers or {})})
    with urlopen(request, timeout=22) as response:
        return json.loads(response.read(9_000_000).decode("utf-8"))


def normalized_job(job):
    job = dict(job)
    job["company"] = textify(job.get("company") or job.get("employer"))[:130]
    job["title"] = textify(job.get("title"))[:200]
    job["description"] = textify(job.get("description"))[:8000]
    job["location"] = textify(job.get("location"))[:200]
    job["source"] = textify(job.get("source"))[:120]
    job["url"] = make_url(job.get("url"))
    job["work_mode"] = textify(job.get("work_mode") or ("Remote" if "remote" in job["location"].lower() else "Unspecified"))
    job["posted_at"] = date_parser(job.get("posted_at"))
    job["salary"] = textify(job.get("salary"))[:150]
    job["location_restrictions"] = job.get("location_restrictions") or []
    job["timezone_restrictions"] = job.get("timezone_restrictions") or []
    job["key"] = str(job.get("key") or ("url:" + hashlib.sha256(job["url"].encode()).hexdigest()[:24]))
    return job


def fetch_remotive():
    data = get_json("https://remotive.com/api/remote-jobs?limit=500")
    return [normalized_job({"key": "remotive:" + str(x.get("id")), "company": x.get("company_name"), "title": x.get("title"), "location": x.get("candidate_required_location"), "work_mode": "Remote", "url": x.get("url"), "description": x.get("description"), "posted_at": x.get("publication_date"), "salary": x.get("salary"), "source": "Remotive (remote; some jobs posted with 24h delay)"}) for x in data.get("jobs", [])]


def fetch_himalayas(queries):
    """Small targeted search; provider refreshes daily, no need to crawl every page."""
    output = []
    headers = {"Authorization": "Bearer " + os.environ["HIMALAYAS_API_KEY"]} if os.getenv("HIMALAYAS_API_KEY") else None
    # General GIS discovery plus India-specific remote searches and Gulf relocation search.
    searches = [{"q": q} for q in queries[:8]]
    searches += [{"q": q, "country": "IN"} for q in ("GIS", "geospatial")]
    searches += [{"q": "GIS", "country": "AE"}, {"q": "GIS", "country": "SA"}]
    for search in searches:
        qs = urlencode({**search, "sort": "recent", "page": 1})
        page = get_json("https://himalayas.app/jobs/api/search?" + qs, headers=headers)
        for x in page.get("jobs", []):
            restrictions = x.get("locationRestrictions") or []
            zones = x.get("timezoneRestrictions") or []
            restricted_names = [r.get("name", "") if isinstance(r, dict) else str(r) for r in restrictions]
            restricted_iso = [r.get("alpha2", "") if isinstance(r, dict) else str(r) for r in restrictions]
            loc = ", ".join(filter(None, restricted_names)) or "Worldwide (per platform)"
            sal_min, sal_max = x.get("minSalary"), x.get("maxSalary")
            salary = f"{x.get('currency', '')} {sal_min or ''}–{sal_max or ''} / {x.get('salaryPeriod','annual')}" if (sal_min is not None or sal_max is not None) else ""
            output.append(normalized_job({"key": "himalayas:" + str(x.get("guid") or x.get("applicationLink")), "company": x.get("companyName"), "title": x.get("title"), "location": loc, "work_mode": "Remote", "url": x.get("applicationLink"), "description": x.get("description") or x.get("excerpt"), "posted_at": x.get("pubDate"), "salary": salary, "source": "Himalayas (remote)", "location_restrictions": restricted_iso, "timezone_restrictions": zones}))
    return list({job["key"]: job for job in output}.values())


def fetch_arbeitnow(pages=2):
    output = []
    for page_num in range(1, min(4, max(1, int(pages))) + 1):
        params = urlencode({"page": page_num})
        data = get_json("https://www.arbeitnow.com/api/job-board-api?" + params)
        for x in data.get("data", []):
            output.append(normalized_job({"key": "arbeitnow:" + str(x.get("slug") or x.get("url")), "company": x.get("company_name"), "title": x.get("title"), "description": x.get("description"), "location": x.get("location"), "url": x.get("url"), "work_mode": "Remote" if x.get("remote") else "On-site/Hybrid/Unspecified", "posted_at": x.get("created_at"), "source": "Arbeitnow (Europe)"}))
        if not data.get("links", {}).get("next"):
            break
    return output


def fetch_adzuna(config):
    """Optional credentialed API; country codes are user-configurable and can fail per market."""
    app_id = os.getenv("ADZUNA_APP_ID", "").strip()
    app_key = os.getenv("ADZUNA_APP_KEY", "").strip()
    if not app_id or not app_key:
        return [], ["Adzuna not connected: add ADZUNA_APP_ID and ADZUNA_APP_KEY for wider country search"]
    jobs, errors = [], []
    for country in config.get("adzuna_country_codes", ["in", "gb", "de", "fr", "nl", "au"]):
        if not re.fullmatch(r"[a-z]{2}", str(country)):
            continue
        for phrase in config.get("adzuna_searches", ["GIS analyst", "geospatial"]):
            params = {"app_id": app_id, "app_key": app_key, "what": phrase, "results_per_page": 35, "max_days_old": 8, "content-type": "application/json"}
            url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1?" + urlencode(params)
            try:
                resp = get_json(url)
                for x in resp.get("results", []):
                    loc = x.get("location") or {}
                    salary = "" if x.get("salary_min") is None and x.get("salary_max") is None else f"{x.get('salary_min', '')}–{x.get('salary_max', '')} (market currency, amount/pay period verify)"
                    jobs.append(normalized_job({"key": "adzuna:" + country + ":" + str(x.get("id")), "company": (x.get("company") or {}).get("display_name") or "Company not specified", "title": x.get("title"), "description": x.get("description"), "location": loc.get("display_name") or ", ".join(loc.get("area", []) if isinstance(loc.get("area"), list) else []), "url": x.get("redirect_url"), "posted_at": x.get("created"), "work_mode": "Unspecified", "salary": salary, "source": "Adzuna (" + country.upper() + ")"}))
            except Exception as exc:
                # Country coverage is not universal; don't let unsupported markets break other scans.
                errors.append(f"Adzuna {country.upper()}/{phrase}: {str(exc)[:140]}")
    return jobs, errors


def discover(config):
    notes, gathered = [], []
    boards = json.loads(BOARDS.read_text(encoding="utf-8"))["boards"]
    tasks = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        for board in boards:
            if board.get("enabled", False):
                tasks.append(("ATS: " + board["company"], pool.submit(watcher.fetch_board, board)))
        if config.get("sources", {}).get("remotive", True):
            tasks.append(("Remotive", pool.submit(fetch_remotive)))
        if config.get("sources", {}).get("himalayas", True):
            tasks.append(("Himalayas", pool.submit(fetch_himalayas, config.get("remote_keywords", []))))
        if config.get("sources", {}).get("arbeitnow", True):
            tasks.append(("Arbeitnow", pool.submit(fetch_arbeitnow, config.get("arbeitnow_pages", 2))))
        for label, future in tasks:
            try:
                jobs = future.result()
                gathered.extend(jobs)
                notes.append(f"{label}: fetched {len(jobs)} raw listings")
            except Exception as exc:
                notes.append(f"ERROR {label}: {str(exc)[:170]}")
    if config.get("sources", {}).get("adzuna", False):
        data, issues = fetch_adzuna(config)
        gathered.extend(data)
        notes.append(f"Adzuna: fetched {len(data)} raw listings")
        notes.extend("WARN " + issue for issue in issues)
    if config.get("sources", {}).get("gmail_alerts", False):
        alerts, issues = watcher.fetch_gmail_alerts()
        gathered.extend(alerts)
        notes.append(f"Gmail alerts: found {len(alerts)} links")
        notes.extend("WARN " + issue for issue in issues)
    return gathered, notes


def geo_classify(job):
    loc = job["location"].lower()
    mode = job["work_mode"].lower()
    remote = "remote" in mode or "work from home" in loc or "wfh" in loc
    restrictions = job.get("location_restrictions") or []
    restricted_iso = {r.upper() for r in restrictions if isinstance(r, str)}
    if "Himalayas" in job["source"]:
        # An empty country restriction means worldwide, but timezone still needs review.
        eligibility = ("Potentially India-eligible; check timezone" if not restricted_iso else
                       "India allowed by location restriction; check timezone" if "IN" in restricted_iso else "Not India-eligible for remote work")
    elif remote and any(x in loc for x in INELIGIBLE_REMOTE):
        eligibility = "Not India-eligible for remote work"
    elif remote and any(x in loc for x in INDIA_TERMS):
        eligibility = "India likely allowed; confirm with employer"
    elif remote and ("worldwide" in loc or "anywhere" in loc or "global" in loc):
        eligibility = "Potentially India-eligible; confirm with employer"
    elif remote:
        eligibility = "India remote eligibility unknown; verify"
    else:
        eligibility = "Not applicable (on-site or unspecified)"
    if any(x in loc for x in INDIA_TERMS) or ("IN" in restricted_iso):
        region = "India"
    elif any(x in loc for x in MIDDLE_EAST_TERMS):
        region = "Middle East"
    elif any(x in loc for x in EUROPE_TERMS):
        region = "Europe"
    elif remote and "not india-eligible" not in eligibility.lower() and ("worldwide" in loc or "anywhere" in loc or "global" in loc or loc in ("", "remote", "not specified")):
        region = "Worldwide remote"
    else:
        region = "Other / review"
    return region, eligibility


def fit_score(job, days=7):
    title = job["title"].lower()
    desc = job["description"].lower()
    if not title or not job["url"] or not job["company"]:
        return -100, "Missing company/title/link"
    if "gas insulated switchgear" in (title + " " + desc) or "switchgear" in title:
        return -100, "Electrical GIS (not geospatial)"
    if not any(x in title for x in TITLE_POSITIVE):
        return -100, "Unrelated job title"
    # Generic 'Data Analyst' is only relevant with strong spatial evidence.
    if any(x in title for x in ("data analyst", "python developer", "environmental")) and not any(x in desc for x in GOOD_DETAILS):
        return -100, "Generic non-spatial role"
    score = 7
    for keyword, points in SKILL_TERMS.items():
        if keyword in title: score += points * 2
        elif keyword in desc: score += points
    if any(x in title for x in ("analyst", "associate", "junior", "specialist", "technician", "intern", "research assistant")):
        score += 5
    experience_flag = "Check requirements"
    if any(x in title for x in SENIOR_TITLES):
        score -= 13
        experience_flag = "Likely senior — stretch"
    text = title + " " + desc[:7000]
    matches = [int(n) for n in re.findall(r"(?:minimum\s+of\s+)?(\d{1,2})\s*\+?\s*(?:years|yrs)\s*(?:of)?\s*(?:relevant\s*)?experience", text)]
    if matches and min(matches) >= 4:
        score -= 12
        experience_flag = f"Requires ~{min(matches)}+ years — stretch"
    elif matches:
        experience_flag = f"Mentions {min(matches)} years"
    posted = job.get("posted_at")
    if posted and posted > NOW + timedelta(days=1):
        return -100, "Invalid future posting date"
    if posted:
        age_days = (NOW - posted).total_seconds() / 86400
        if age_days <= days:
            score += 8
            freshness = "Posted in last 7 days"
        elif age_days <= 30:
            freshness = "Posted 8–30 days ago"
        else:
            freshness = "Posted >30 days ago"
            score -= 5
    else:
        freshness = "No reliable published date"
    # Store freshness without a separate mutable global.
    job["freshness"] = freshness
    return score, experience_flag


def enrich(raw, threshold=8, recent_days=7, allow_old=False):
    job = normalized_job(raw)
    score, experience_flag = fit_score(job, days=recent_days)
    if score < threshold and not (job["source"].startswith("Gmail job alert") and any(x in job["title"].lower() for x in TITLE_POSITIVE)):
        return None
    region, eligibility = geo_classify(job)
    if job["source"].startswith("Gmail job alert"):
        # Alert emails are only *leads*; location/title cannot safely be inferred from an email subject.
        region = "Other / review"
        eligibility = "Unknown — check the actual job page"
        score = max(score, threshold)
    elif eligibility == "Not India-eligible for remote work":
        if region == "Middle East":
            eligibility = "Not India-eligible for remote work; relocation may be needed"
        else:
            return None
    if region == "Other / review" and "remote" not in job["work_mode"].lower() and not job["source"].startswith("Gmail job alert"):
        return None  # Avoid USA/Canada on-site jobs; relocation priority is Middle East.
    # Europe on-site/hybrid not a main target; preserve Middle East relocation.
    if region == "Europe" and "remote" not in job["work_mode"].lower():
        return None
    if not allow_old and job["freshness"] == "Posted >30 days ago":
        return None
    job.update({"region": region, "india_remote_eligibility": eligibility,
                "fit_score": score, "experience_flag": experience_flag,
                "discovered_at": NOW.isoformat(), "notes": "Verify job still active, requirements, salary, work authorization and application instructions"})
    if job["source"].startswith("Gmail job alert"):
        job["notes"] = "UNVERIFIED: link extracted from notification email; confirm the vacancy before applying"
    return job


def dedupe(jobs):
    result = {}
    for job in jobs:
        if not job.get("url"): continue
        # Same destination can appear in multiple feeds. Keep the highest-scoring record.
        url_key = make_url(job["url"])
        key = url_key or job["key"]
        existing = result.get(key)
        if existing is None or job["fit_score"] > existing["fit_score"]:
            result[key] = job
    return sorted(result.values(), key=lambda j: (-j["fit_score"], 0 if j["freshness"] == "Posted in last 7 days" else 1, j["company"].lower()))


def load_seen():
    if not STATE.exists(): return set()
    data = json.loads(STATE.read_text(encoding="utf-8"))
    return set(data.get("known_keys", []))


def csv_rows(path, rows, fields=CSV_FIELDS):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for x in rows:
            row = {k: x.get(k, "") for k in fields}
            row["job_key"] = x.get("key", row.get("job_key", ""))
            if "posted_at" in fields and isinstance(x.get("posted_at"), datetime):
                row["posted_at"] = x["posted_at"].isoformat()
            writer.writerow({k: safe_csv(v) for k, v in row.items()})


def existing_95_audit(current):
    with LEGACY.open("r", encoding="utf-8-sig", newline="") as f:
        old = list(csv.DictReader(f))
    official = [j for j in current if "Official" in j["source"]]
    out = []
    for row in old:
        employer = re.sub(r"[^a-z0-9]", "", row["employer"].lower())
        role = re.sub(r"[^a-z0-9]", "", row["role"].lower())
        matches = [j for j in official if re.sub(r"[^a-z0-9]", "", j["company"].lower()) == employer and re.sub(r"[^a-z0-9]", "", j["title"].lower()) == role]
        # Exact title+employer match is one evidence point; not guarantee of full eligibility.
        status = "Official ATS title/company match; verify requirements" if matches else "Not confirmed open; manual employer check needed"
        source_link = matches[0]["url"] if matches else row["source_url"]
        if row["link_type"].lower() in ("results page", "search page") and not matches:
            status = "Search-results link only — not a verified vacancy"
        out.append({"job_id": row["job_id"], "employer": row["employer"], "role": row["role"], "region": row["region"], "status": status, "best_link": source_link, "original_link_type": row["link_type"]})
    return out


def drafts(new_jobs):
    parts = ["# Review-only application notes", "", "No job applications or recruiter emails are sent by this program. Tailor to the actual description and verify eligibility before applying.", ""]
    for job in new_jobs[:25]:
        if job["source"].startswith("Gmail job alert"):
            continue
        parts += [f"## {job['company']} — {job['title']}", f"Apply / original source: {job['url']}", "", "Hello Hiring Team,", "", f"I am interested in the {job['title']} opportunity at {job['company']}. I have one year of professional GIS experience using QGIS, ArcGIS, Google Earth Engine, satellite imagery and spatial analysis for climate risk and disaster management, together with Python and SQL-based workflows. I would welcome the chance to discuss how I could contribute to your team.", "", "Best regards,", "[Your name]", ""]
    return "\n".join(parts)


def render_report(jobs, new, warnings, audit):
    groups = ["India", "Worldwide remote", "Middle East", "Europe", "Other / review"]
    L = ["# GIS Job Hunter V2 — latest cloud scan", "", f"Scan: {NOW.strftime('%d %b %Y, %H:%M UTC')}", "", f"- Matches now visible in supported sources: **{len(jobs)}**", f"- New to YOUR tracker: **{len(new)}** (not the same as newly posted)", f"- New to tracker with published dates in past 7 days: **{sum(x['freshness']=='Posted in last 7 days' for x in new)}**", f"- Original 95 lead audit: **{sum('Official ATS title/company match' in x['status'] for x in audit)}** exact employer+title matches; other leads require checking", "- No application forms or recruiter emails submitted.", "", "## Source diagnostics", ""]
    L += ["- " + x for x in warnings] or ["- None"]
    for group in groups:
        selected = [x for x in new if x["region"] == group]
        L += ["", f"## {group}: {len(selected)} newly discovered matches", ""]
        for j in selected[:30]:
            post_date = j["posted_at"].strftime("%Y-%m-%d") if j["posted_at"] else "unknown"
            L += [f"- **{j['company']} — {j['title']}** · {j['location']} · score {j['fit_score']}", f"  - {j['url']}", f"  - Posted: {post_date} | {j['freshness']} | {j['work_mode']} | {j['india_remote_eligibility']}", f"  - Source: {j['source']} | Experience: {j['experience_flag']}" ]
        if len(selected) > 30:
            L.append(f"- ...and {len(selected)-30} more in `reports/new_jobs.csv`.")
    L += ["", "## Important limitations", "", "An API listing can be withdrawn at any time. 'New' means newly discovered by this pipeline, not posted today. Remote work may have geographic, employment and timezone restrictions. Generic links from the original 95 are not proof of an open vacancy. Unknown salaries are retained, not guessed.", "", "Open `reports/new_jobs.csv` for all new matches and `reports/Original_95_Audit.csv` for the legacy audit.", ""]
    return "\n".join(L)


def send_email(message, n, force=False):
    account = os.getenv("GMAIL_ADDRESS", "").strip()
    password = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not account or not password:
        print("Email not configured; GitHub artifacts will contain the report instead.")
        return False
    if not n and os.getenv("EMAIL_ON_EMPTY", "true").lower() != "true" and not force:
        return False
    email = EmailMessage()
    email["From"] = account
    email["To"] = account  # digest ONLY to the owner's account, never employers
    email["Subject"] = f"GIS Job Hunter V2: {n} new leads ({NOW.strftime('%Y-%m-%d')})"
    email.set_content(message[:230000])
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=25) as client:
        client.login(account, password)
        client.send_message(email)
    return True


def main():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    all_fetched, warnings = discover(config)
    evaluated = [enrich(x, threshold=config.get("minimum_fit_score", 10), recent_days=config.get("recent_days", 7), allow_old=config.get("include_over_30_days", False)) for x in all_fetched]
    results = dedupe([x for x in evaluated if x])
    # Avoid duplicate messages from the same job across two different job providers.
    previous = load_seen()
    new = [j for j in results if j["key"] not in previous and make_url(j["url"]) not in previous]
    audit = existing_95_audit(results)
    report = render_report(results, new, warnings, audit)
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "latest.md").write_text(report, encoding="utf-8")
    (REPORTS / "drafts_to_review.md").write_text(drafts(new), encoding="utf-8")
    csv_rows(REPORTS / "all_matching.csv", results)
    csv_rows(REPORTS / "new_jobs.csv", new)
    csv_rows(REPORTS / "posted_last_7_days.csv", [j for j in results if j["freshness"] == "Posted in last 7 days"])
    csv_rows(REPORTS / "Original_95_Audit.csv", audit, fields=["job_id", "employer", "role", "region", "status", "best_link", "original_link_type"])
    # Persist source health counters, never credentials or full job descriptions.
    (REPORTS / "run_stats.json").write_text(json.dumps({"run_utc": NOW.isoformat(), "raw_fetched": len(all_fetched), "matched": len(results), "new_leads": len(new), "new_with_verified_recent_post_dates": sum(j["freshness"] == "Posted in last 7 days" for j in new), "source_notes": warnings}, indent=2), encoding="utf-8")
    print(f"V2 scan: {len(all_fetched)} fetched, {len(results)} filtered, {len(new)} first seen. Warnings: {len(warnings)}")
    # Sending failures must not re-alert users endlessly; GitHub only persists on successful runs.
    send_email(report, len(new))
    previous.update(j["key"] for j in results)
    previous.update(make_url(j["url"]) for j in results)
    STATE.parent.mkdir(exist_ok=True, parents=True)
    STATE.write_text(json.dumps({"known_keys": sorted(x for x in previous if x), "last_run": NOW.isoformat()}, indent=2) + "\n", encoding="utf-8")
    return {"raw": len(all_fetched), "matched": len(results), "new": len(new), "source_messages": warnings}


if __name__ == "__main__":
    main()
