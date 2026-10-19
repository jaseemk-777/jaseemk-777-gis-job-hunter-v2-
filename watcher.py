"""Twice-daily GIS job discovery from public employer ATS feeds + optional Gmail-label alerts.
No auto-applications or unsolicited messages. Standard-library-only Python 3.12.
"""
import csv
import email
from email import policy
from email.message import EmailMessage
from html import unescape
from html.parser import HTMLParser
import hashlib
import imaplib
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlsplit, urlunsplit, parse_qsl, urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
BOARDS_PATH = ROOT / "boards.json"
STATE_PATH = ROOT / "data" / "seen.json"
LEGACY_PATH = ROOT / "data" / "Original_95_Job_Leads.csv"
REPORTS = ROOT / "reports"
NOW = datetime.now(timezone.utc)

KEYWORDS = {
    "geospatial": 6, "remote sensing": 6, "geographic information": 6,
    "gis analyst": 7, "gis specialist": 7, "gis technician": 4,
    "gis developer": 5, "earth observation": 5, "spatial analyst": 5,
    "cartograph": 4, "geoinformatics": 6, "spatial data": 4,
    "climate risk": 4, "climate vulnerability": 4, "satellite": 3,
    "flood": 2, "disaster": 2, "google earth engine": 4,
    "arcgis": 3, "qgis": 3, "urban planning": 3,
    "geography": 4, "map analyst": 5, "mapping": 3,
    "environmental": 1, "geopandas": 2, "python": 1, "postgis": 2,
}
TITLE_HITS = ("gis", "geo", "spatial", "remote sensing", "satellite", "cartograph", "mapping", "earth observation", "climate", "geography", "disaster", "urban planner")
DISQUALIFY = ("gas insulated switchgear", "gas-insulated switchgear", "high voltage switchgear", "substation protection", "power transformers")
ALERT_URL_RX = re.compile(r"https?://[^\s<>\"']+", re.I)
ALERT_HOSTS = ("linkedin.com", "indeed.com", "indeed.co.in", "naukri.com", "naukrigulf.com", "lever.co", "greenhouse.io", "ashbyhq.com", "remotive.com", "myworkdayjobs.com", "workdayjobs.com")


class HTMLCleaner(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.links = []
    def handle_data(self, data):
        self.parts.append(data)
    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            link = dict(attrs).get("href")
            if link:
                self.links.append(unescape(link))


def plain(html):
    c = HTMLCleaner()
    c.feed(str(html or ""))
    return " ".join(c.parts)


def is_https_url(value):
    p = urlparse(str(value or ""))
    return p.scheme == "https" and bool(p.hostname)


def get_json(url):
    if not is_https_url(url):
        raise ValueError("Only HTTPS job feeds are allowed")
    req = Request(url, headers={"User-Agent": "GIS-Job-Watcher/1.0 (personal job research)", "Accept": "application/json"})
    with urlopen(req, timeout=18) as resp:
        if int(resp.headers.get("Content-Length", "0") or 0) > 8_000_000:
            raise ValueError("Job-feed response too large")
        return json.loads(resp.read(8_000_001).decode("utf-8"))


def fetch_board(board):
    """Return (jobs, errors) from a configured, public official ATS feed."""
    company, provider, slug = (str(board.get(k, "")).strip() for k in ("company", "provider", "slug"))
    if not board.get("enabled", False):
        return []
    if not re.fullmatch(r"[\w-]{2,90}", slug, flags=re.ASCII):
        raise ValueError(f"Invalid ATS board slug for {company}")
    if provider == "greenhouse":
        data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
        items = data.get("jobs", [])
        return [{"id": f"greenhouse:{slug}:{j.get('id')}", "employer": company,
                 "title": j.get("title", ""), "location": (j.get("location") or {}).get("name", ""),
                 "url": j.get("absolute_url", ""), "description": plain(j.get("content", "")),
                 "date_evidence": "updated_at=" + str(j.get("updated_at", "not provided")),
                 "source": "Official Greenhouse job board", "checked_at": NOW.isoformat()}
                for j in items if j.get("id")]
    if provider == "lever":
        data = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
        return [{"id": f"lever:{slug}:{j.get('id')}", "employer": company,
                 "title": j.get("text", ""), "location": (j.get("categories") or {}).get("location", ""),
                 "url": j.get("hostedUrl", ""), "description": plain(j.get("descriptionPlain") or j.get("description", "")),
                 "date_evidence": "Created date not guaranteed; API timestamp=" + str(j.get("createdAt", "not provided")),
                 "source": "Official Lever job board", "checked_at": NOW.isoformat()}
                for j in data if j.get("id")]
    if provider == "ashby":
        data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        return [{"id": f"ashby:{slug}:{j.get('id') or j.get('jobUrl')}", "employer": company,
                 "title": j.get("title", ""), "location": j.get("location", ""),
                 "url": j.get("jobUrl", ""), "description": plain(j.get("descriptionHtml") or j.get("descriptionPlain", "")),
                 "date_evidence": "publishedAt=" + str(j.get("publishedAt", "not provided")),
                 "source": "Official Ashby job board", "checked_at": NOW.isoformat()}
                for j in data.get("jobs", []) if j.get("jobUrl")]
    raise ValueError(f"Unsupported ATS provider: {provider}")


def canonical_url(url):
    u = urlsplit(str(url or "").strip().rstrip(".,);>"))
    if u.scheme != "https" or not u.hostname:
        return ""
    host = u.hostname.lower().removeprefix("www.")
    # Remove common marketing query params but preserve job IDs in other parameters.
    query = urlencode([(k, v) for k, v in parse_qsl(u.query) if not k.lower().startswith("utm_") and k.lower() not in ("trk", "trackingid", "ref", "source")])
    return urlunsplit(("https", host, u.path.rstrip("/") or "/", query, ""))


def allowed_job_alert_url(url):
    normalized = canonical_url(url)
    if not normalized:
        return ""
    p = urlparse(normalized)
    host = p.hostname or ""
    if not any(host == h or host.endswith("." + h) for h in ALERT_HOSTS):
        return ""
    path = p.path.lower()
    # Ignore general landing pages and generic jobs search pages.
    if ("linkedin.com" in host and "/jobs/view/" not in path):
        return ""
    if ("naukri.com" in host and "job-listings" not in path):
        return ""
    if ("indeed" in host and not ("viewjob" in path or "jk=" in p.query)):
        return ""
    if ("remotive.com" in host and "/remote-jobs/" not in path):
        return ""
    if ("greenhouse.io" in host and "/jobs/" not in path):
        return ""
    return normalized


def fetch_gmail_alerts():
    """Optional, read-only via user-labelled Gmail folder. These are unverified leads."""
    if os.getenv("GMAIL_ALERTS_ENABLED", "").lower() not in ("yes", "true", "1"):
        return [], []
    username = os.getenv("GMAIL_ADDRESS", "").strip()
    password = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not username or not password:
        return [], ["Gmail alert reading enabled, but Gmail secrets are missing"]
    label = os.getenv("GMAIL_ALERT_LABEL", "GIS-JOB-ALERTS")
    alerts, errors = [], []
    try:
        with imaplib.IMAP4_SSL("imap.gmail.com", 993, ssl_context=ssl.create_default_context(), timeout=20) as conn:
            conn.login(username, password)
            status, _ = conn.select('"' + label.replace('"', "") + '"', readonly=True)
            if status != "OK":
                return [], [f"Gmail label {label} unavailable over IMAP; enable label's IMAP visibility"]
            day_since = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%d-%b-%Y")
            st, resp = conn.search(None, "SINCE", day_since)
            if st != "OK":
                return [], ["Cannot search labelled Gmail messages"]
            for msg_id in resp[0].split()[-35:]:
                st, content = conn.fetch(msg_id, "(RFC822)")
                if st != "OK":
                    continue
                raw = next((part[1] for part in content if isinstance(part, tuple)), None)
                if not raw:
                    continue
                msg = email.message_from_bytes(raw, policy=policy.default)
                subject = str(msg.get("Subject", "Job alert"))[:160]
                bodies = []
                parts = msg.walk() if msg.is_multipart() else [msg]
                for part in parts:
                    if part.get_content_type() in ("text/html", "text/plain"):
                        try:
                            bodies.append(str(part.get_content()))
                        except (UnicodeError, LookupError):
                            continue
                urls = []
                for body in bodies:
                    urls.extend(ALERT_URL_RX.findall(body))
                    if "<a" in body:
                        parser = HTMLCleaner()
                        parser.feed(body)
                        urls.extend(parser.links)
                for url in list(dict.fromkeys(filter(None, (allowed_job_alert_url(u) for u in urls))))[:15]:
                    alerts.append({"id": "alert:" + hashlib.sha256(url.encode()).hexdigest()[:20],
                                   "employer": "Verify on linked employer page", "title": subject,
                                   "location": "See individual posting", "url": url,
                                   "description": "Job link extracted from a user-labelled notification email; not verified as active.",
                                   "date_evidence": "Email received: " + str(msg.get("Date", "unknown")),
                                   "source": "Gmail job alert — unverified", "checked_at": NOW.isoformat()})
    except Exception as exc:
        errors.append("Gmail label scan failed: " + str(exc)[:240])
    return alerts, errors


def rating(item):
    title = plain(item.get("title", "")).lower()
    detail = plain(item.get("description", "")).lower()
    text = f"{title} {detail}"
    if any(x in text for x in DISQUALIFY) and not ("geospatial" in text or "geographic information" in text):
        return -100
    if not any(word in title for word in TITLE_HITS):
        # Generic software/data science jobs only qualify with strong spatial description.
        if not any(x in detail for x in ("geospatial", "remote sensing", "earth observation", "geographic information systems", "qgis", "arcgis")):
            return 0
    score = 0
    for word, points in KEYWORDS.items():
        if word in title:
            score += points * 2
        elif word in detail:
            score += points
    if title.startswith("senior") or "principal" in title or "director" in title:
        score -= 6
    years = re.search(r"\b(\d{1,2})\s*\+?\s*years?\s*(?:of\s*)?experience", text)
    if years and int(years.group(1)) >= 5:
        score -= 6
    return score


def load_legacy():
    with LEGACY_PATH.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows


def report_text(new_jobs, all_current, legacy_count, errors):
    timestamp = NOW.strftime("%d %b %Y %H:%M UTC")
    def line(j):
        return f"- **{j['employer']} — {j['title']}** ({j['location'] or 'location not specified'}; fit score {j['score']})  \n  {j['url']}  \n  *{j['source']}* · {j['date_evidence']}"
    lines = [f"# GIS job scan — {timestamp}", "", f"- New-to-this-tracker matching leads: **{len(new_jobs)}**", f"- All matching jobs currently visible on configured ATS feeds / alert messages: **{len(all_current)}**", f"- Original job-lead inventory: **{legacy_count}** (historical; **not verified active**)", "- 'New' means not previously recorded in the tracker, **not necessarily posted in the past week**.", "- Remote listings must be checked for eligibility to work from India.", "- No employer applications or recruitment emails have been sent.", ""]
    if errors:
        lines.extend(["## Source warnings", *["- " + e for e in errors], ""])
    lines.append("## New matching listings and job-alert leads")
    lines.extend(map(line, new_jobs[:40]))
    if not new_jobs:
        lines.append("No newly discovered matches this run. Confirm configured job boards and email alerts are working.")
    if len(new_jobs) > 40:
        lines.append(f"...plus {len(new_jobs)-40} additional listings in latest.json")
    lines.extend(["", "## Next steps", "Open each direct posting, verify the deadline/qualifications/remote eligibility, and apply on the employer's website. For emailed alerts, treat links as unverified until opened."])
    return "\n".join(lines) + "\n"


def make_drafts(new_jobs):
    result = ["# Application message templates — review before using", "", "These are **not sent** by the watcher. Verify vacancies and customize the recipient and role first.", ""]
    for job in new_jobs[:12]:
        if job["source"].startswith("Gmail job alert"):
            continue
        employer, role = job["employer"], job["title"]
        result.extend([f"## {employer} — {role}", f"Application: {role}", "",
                       f"Hello Hiring Team,\n\nI am interested in the {role} opportunity at {employer}. I have over a year of professional GIS experience working on satellite imagery, QGIS, Google Earth Engine, geospatial analysis, climate-risk assessments and disaster risk reduction. I have also worked with Python, spatial data validation and reporting. I would welcome the opportunity to discuss how this experience could contribute to your team.\n\nKind regards,\n[Your name]", "",
                       f"Apply: {job['url']}", ""])
    return "\n".join(result) + "\n"


def send_digest(report_text_content, count):
    address = os.getenv("GMAIL_ADDRESS", "").strip()
    pwd = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not address or not pwd:
        print("Gmail secrets not configured; reports saved locally and to GitHub. No email sent.")
        return False
    msg = EmailMessage()
    msg["From"] = address
    msg["To"] = address  # Mail the digest to yourself ONLY.
    msg["Subject"] = f"GIS job scan: {count} new matching lead(s) | {NOW.strftime('%Y-%m-%d')}"
    msg.set_content(report_text_content[:240_000])
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=25, context=ctx) as s:
        s.login(address, pwd)
        s.send_message(msg)
    print("Digest emailed to configured account (not to employers).")
    return True


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
    seen = set(state.get("known_keys", []))
    board_cfg = json.loads(BOARDS_PATH.read_text(encoding="utf-8"))
    errors, candidates = [], []
    for board in board_cfg.get("boards", []):
        if not board.get("enabled", False):
            continue
        try:
            candidates.extend(fetch_board(board))
            print(f"Checked {board.get('company')}: retrieved matching data")
        except Exception as exc:
            errors.append(f"{board.get('company')}: {str(exc)[:240]}")
    alerts, alert_errors = fetch_gmail_alerts()
    candidates.extend(alerts)
    errors.extend(alert_errors)
    jobs = []
    emitted = set()
    for j in candidates:
        if not is_https_url(j.get("url", "")):
            continue
        key = j.get("id") or "url:" + canonical_url(j["url"])
        if key in emitted:
            continue
        emitted.add(key)
        score = rating(j)
        # Trust only a title match for email alert (email Subject might be generic).
        if j["source"].startswith("Gmail job alert") and any(x in j["title"].lower() for x in TITLE_HITS):
            score = max(score, 5)
        if score < 5:
            continue
        jobs.append({**j, "key": key, "score": score})
    jobs.sort(key=lambda j: (-j["score"], j["employer"], j["title"]))
    new = [job for job in jobs if job["key"] not in seen]
    legacy_count = len(load_legacy())
    report = report_text(new, jobs, legacy_count, errors)
    (REPORTS / "latest.md").write_text(report, encoding="utf-8")
    (REPORTS / "latest.json").write_text(json.dumps({"run_utc": NOW.isoformat(), "new_jobs": new, "all_matching": jobs, "warnings": errors, "legacy_count": legacy_count}, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORTS / "outreach_drafts.md").write_text(make_drafts(new), encoding="utf-8")
    print(f"Scan complete: {len(jobs)} matching, {len(new)} new, {legacy_count} imported legacy leads, {len(errors)} source warnings")
    for w in errors:
        print("SOURCE WARNING: " + w)
    # If sending fails, workflow will be marked failed and seen state is not saved; retry does not lose leads.
    send_digest(report, len(new))
    seen.update(job["key"] for job in jobs)
    state = {"known_keys": sorted(seen), "last_run": NOW.isoformat()}
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if len(errors) == sum(1 for b in board_cfg.get("boards", []) if b.get("enabled")) and not alerts:
        print("Warning: all enabled public job feeds failed to return results.")


if __name__ == "__main__":
    main()
