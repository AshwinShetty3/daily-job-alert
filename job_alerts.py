"""Daily personal job digest. Only public APIs/RSS and the owner's Gmail."""
import argparse
import base64
import hashlib
import html
import json
import logging
import os
import re
import smtplib
import ssl
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
SENIOR = re.compile(r"\b(senior|sr\.?|lead|principal|staff|architect|manager|head|director)\b", re.I)
ROLE = re.compile(r"\b(dev\s*ops|devsecops|site reliability|sre|platform engineer|kubernetes engineer|cloud (?:infrastructure )?engineer|aws (?:devops|engineer)|infrastructure engineer|production engineer|release engineer|build engineer)\b", re.I)
IRRELEVANT = re.compile(r"\b(sales|account executive|business development|recruiter|marketing)\b", re.I)
EXP = re.compile(r"(?:(up to|at least|minimum(?: of)?|more than|over)\s*)?(\d+(?:\.\d+)?)\s*(?:[-–—]|to)\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?)|(?:(up to|at least|minimum(?: of)?|more than|over)\s*)?(\d+(?:\.\d+)?)\s*(\+)?\s*(?:years?|yrs?)", re.I)
ENTRY = re.compile(r"\b(fresher|entry[- ]level|junior|associate|trainee|engineer (?:i|ii|1|2))\b", re.I)
INDIA = re.compile(r"\b(india|bangalore|bengaluru|hyderabad|pune|chennai|delhi|gurugram|gurgaon|noida|mumbai|kolkata|ahmedabad|kochi|ncr)\b", re.I)
COUNTRIES = re.compile(r"\b(usa|united states|us|uk|united kingdom|canada|germany|netherlands|uae|united arab emirates|singapore|australia|worldwide|anywhere|global)\b", re.I)


def plain(value):
    return BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)


def stamp(value):
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000 if value > 10**12 else value, UTC)
        date = parse_date(str(value))
        return date.replace(tzinfo=UTC) if date.tzinfo is None else date.astimezone(UTC)
    except (ValueError, TypeError, OverflowError):
        return None


def safe_url(value):
    value = html.unescape(str(value or "")).strip()
    return value if urlparse(value).scheme in ("https", "http") and urlparse(value).netloc else ""


def message_key(message_id):
    return hashlib.sha256(message_id.encode()).hexdigest()


def canonical_url(value):
    p = urlparse(safe_url(value))
    query = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith("utm_") and k.lower() not in {"trk", "trackingid", "ref", "source"}]
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", urlencode(sorted(query)), ""))


@dataclass
class Job:
    title: str
    company: str
    location: str
    source: str
    url: str
    posted: str = ""
    description: str = ""
    experience: str = ""
    mode: str = "Not specified"
    date_basis: str = "Source posting date"
    source_id: str = ""
    seniority: str = ""

    def ids(self):
        norm = lambda s: re.sub(r"\s+", " ", s.strip().lower())
        raw = norm(self.title) + "|" + norm(self.company) + "|" + canonical_url(self.url)
        ids = [hashlib.sha256(raw.encode()).hexdigest()]
        if self.source_id:
            ids.append(hashlib.sha256((self.source + "|" + self.source_id).encode()).hexdigest())
        return ids


def experience(job):
    if SENIOR.search(job.title) or SENIOR.search(job.seniority):
        return False, "Senior-level title or structured seniority"
    # Structured requirement wins; otherwise inspect title + description.
    text = job.experience or (job.title + ". " + job.description)
    requirements = []
    for m in EXP.finditer(text):
        qualifier = (m[1] or m[4] or "").lower()
        low, high = (float(m[2]), float(m[3])) if m[2] else (float(m[5]), None)
        if qualifier == "up to":
            high, low = high if high is not None else low, 0
        # Explicit user exception: 3-5 excluded, even though lower endpoint is 3.
        if low > 3 or (low == 3 and high is not None and high > 3) or (low >= 3 and qualifier in {"over", "more than"}):
            return False, m[0]
        requirements.append(m[0])
    if requirements:
        return True, "; ".join(dict.fromkeys(requirements))
    if job.experience == "Not specified":
        return True, "Not specified"
    if job.experience:
        return True, job.experience + " (no numeric requirement detected)"
    entry = ENTRY.search(text)
    return True, entry[0] if entry else "Not specified"


def eligible(job, now):
    if not ROLE.search(job.title) or IRRELEVANT.search(job.title) or not safe_url(job.url):
        return False
    ok, requirement = experience(job)
    job.experience = requirement
    date = stamp(job.posted)
    if not ok or not date or not now - timedelta(hours=24) <= date <= now:
        return False
    # Unknown locations are held out rather than silently treating remote as worldwide.
    return bool(INDIA.search(job.location) or COUNTRIES.search(job.location))


def make_job(title, company, location, source, url, posted=None, description="", **kw):
    date = stamp(posted)
    description = plain(description)
    mode = kw.pop("mode", "")
    if not mode:
        text = location + " " + description
        mode = "Hybrid" if re.search(r"\bhybrid\b", text, re.I) else "Remote" if re.search(r"\bremote\b", text, re.I) else "Onsite" if re.search(r"\bon[- ]?site\b", text, re.I) else "Not specified"
    return Job(plain(title), plain(company) or "Not specified", plain(location) or "Not specified", source, safe_url(url), date.isoformat() if date else "", description, mode=mode, **kw)


def get(url, **kw):
    response = requests.get(url, timeout=40, headers=kw.pop("headers", {"User-Agent": "PersonalJobDigest/1.0"}), **kw)
    response.raise_for_status()
    return response


def remotive(config, state, now):
    return [make_job(j["title"], j["company_name"], j.get("candidate_required_location"), "Remotive", j["url"], j.get("publication_date"), j.get("description"), mode="Remote", source_id=str(j["id"])) for j in get("https://remotive.com/api/remote-jobs").json()["jobs"]]


def remoteok(config, state, now):
    return [make_job(j["position"], j.get("company"), j.get("location") or "Not specified", "Remote OK", j.get("url"), j.get("epoch") or j.get("date"), j.get("description"), mode="Remote", source_id=str(j.get("id", ""))) for j in get("https://remoteok.com/api").json() if "position" in j]


def himalayas(config, state, now):
    jobs = []
    for query in config["queries"]:
        for page in range(1, int(os.getenv("HIMALAYAS_PAGES", "3")) + 1):
            data = get("https://himalayas.app/jobs/api/search", params={"q": query, "sort": "recent", "page": page}).json()
            rows = data.get("jobs", [])
            for j in rows:
                restrictions = j.get("locationRestrictions") or []
                location = ", ".join(restrictions) if restrictions else "Worldwide (check timezone restrictions)"
                if j.get("timezoneRestrictions"):
                    location += "; UTC offsets: " + str(j["timezoneRestrictions"])
                jobs.append(make_job(j["title"], j.get("companyName"), location, "Himalayas", j.get("applicationLink") or j.get("guid"), j.get("pubDate"), j.get("description"), mode="Remote", source_id=j.get("guid", ""), seniority=", ".join(j.get("seniority") or [])))
            if not rows or all(stamp(j.get("pubDate")) and stamp(j["pubDate"]) < now - timedelta(hours=24) for j in rows):
                break
            time.sleep(1)
    return jobs


def wwr(config, state, now):
    feed = feedparser.parse(get("https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss").content)
    if feed.bozo and not feed.entries:
        raise ValueError("Invalid WWR RSS")
    jobs = []
    for j in feed.entries:
        company, sep, title = j.title.partition(": ")
        description = plain(j.get("summary", ""))
        # RSS often lacks structured location; only explicit geography is accepted.
        location = "Worldwide" if re.search(r"anywhere in the world|worldwide", description, re.I) else description[:500]
        jobs.append(make_job(title if sep else j.title, company if sep else "", location, "We Work Remotely", j.link, j.get("published"), description, mode="Remote", source_id=j.get("id", "")))
    return jobs


def adzuna(config, state, now):
    if not os.getenv("ADZUNA_APP_ID") or not os.getenv("ADZUNA_APP_KEY"):
        return [], ["Adzuna disabled: keys not configured"]
    jobs, warnings = [], []
    for country in config["adzuna_countries"]:
        for query in config["queries"]:
            for page in range(1, int(os.getenv("ADZUNA_PAGES", "1")) + 1):
                try:
                    data = get(f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}", params={"app_id": os.environ["ADZUNA_APP_ID"], "app_key": os.environ["ADZUNA_APP_KEY"], "what": query, "max_days_old": 1, "results_per_page": 50, "sort_by": "date"}).json()
                    for j in data.get("results", []):
                        jobs.append(make_job(j["title"], j.get("company", {}).get("display_name"), j.get("location", {}).get("display_name", "") + ", " + {"in":"India","us":"USA","gb":"UK","ca":"Canada","de":"Germany","nl":"Netherlands","au":"Australia","sg":"Singapore"}[country], "Adzuna", j.get("redirect_url"), j.get("created"), j.get("description"), source_id=str(j.get("id", ""))))
                    if len(data.get("results", [])) < 50:
                        break
                except Exception as error:
                    warnings.append(f"Adzuna {country}: {type(error).__name__}; check account quota/country support")
                    break
    return jobs, list(dict.fromkeys(warnings))


def save_state(state):
    path = ROOT / "data/state.json"
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def jsearch(config, state, now, reserve=True):
    limit = int(os.getenv("JSEARCH_MONTHLY_LIMIT", "0"))
    if not os.getenv("JSEARCH_API_KEY") or limit <= 0:
        return [], ["JSearch disabled: configure key AND verified free monthly request cap"]
    month = now.strftime("%Y-%m")
    used = state.setdefault("jsearch_usage", {}).get(month, 0)
    # Two requests/day maximum; rotate country + keyword coverage to stay inexpensive.
    count = min(2, max(0, limit - used))
    jobs, warnings = [], []
    if not count:
        return [], ["JSearch monthly free request budget exhausted"]
    pairs = [(country, query) for query in config["queries"] for country in config["jsearch_countries"]]
    for n in range(count):
        country, query = pairs[(now.toordinal() * 2 + n) % len(pairs)]
        # Reserve before request; failed requests may count against provider quota.
        used += 1
        state["jsearch_usage"][month] = used
        if reserve:
            save_state(state)
        try:
            data = get("https://jsearch.p.rapidapi.com/search", headers={"X-RapidAPI-Key": os.environ["JSEARCH_API_KEY"], "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}, params={"query": query + " jobs", "country": country, "date_posted": "today", "num_pages": 1, "page": 1}).json()
            for j in data.get("data", []):
                location = ", ".join(str(j[k]) for k in ["job_city", "job_state", "job_country"] if j.get(k))
                names = {"IN":"India", "US":"USA", "GB":"UK", "CA":"Canada", "DE":"Germany", "NL":"Netherlands", "AE":"UAE", "SG":"Singapore", "AU":"Australia"}
                location = ", ".join(names.get(part.strip().upper(), part.strip()) for part in location.split(","))
                exp = j.get("job_required_experience") or {}
                months = exp.get("required_experience_in_months")
                requirement = f"{float(months)/12:g}+ years" if months is not None else ""
                jobs.append(make_job(j["job_title"], j.get("employer_name"), location, (j.get("job_publisher") or "Aggregator") + " via JSearch", j.get("job_apply_link"), j.get("job_posted_at_datetime_utc") or j.get("job_posted_at_timestamp"), j.get("job_description"), experience=requirement, source_id=j.get("job_id", ""), mode="Remote" if j.get("job_is_remote") else ""))
        except Exception as error:
            warnings.append(f"JSearch {country}: {type(error).__name__}; check subscription/quota")
    return jobs, warnings


def parse_alert(body, sender, received, date_policy="strict"):
    """Conservative heuristic adapter: local card context, no job-site visits."""
    platform = next((name for name in ["LinkedIn", "Naukri", "Foundit", "Instahyre"] if name.lower() in sender.lower()), "Gmail alert")
    soup = BeautifulSoup(body, "html.parser")
    jobs = []
    for anchor in soup.find_all("a", href=True):
        title = anchor.get_text(" ", strip=True)
        if not ROLE.search(title) or not safe_url(anchor["href"]):
            continue
        # Use smallest ancestor that has job metadata and exactly one job-title link.
        card = anchor.parent
        for parent in list(anchor.parents)[:8]:
            if parent.name in {"html", "body"}:
                break
            links = [a for a in parent.find_all("a", href=True) if ROLE.search(a.get_text(" ", strip=True))]
            if len(links) > 1:
                break
            card = parent
            if parent.get("data-company") or parent.select_one(".company, .company-name, [data-company]"):
                break
        text = card.get_text(" \n", strip=True)
        def field(names):
            for name in names:
                if card.get("data-" + name):
                    return card["data-" + name]
                node = card.select_one("." + name + ", [data-" + name + "]")
                if node:
                    return node.get("data-" + name) or node.get_text(" ", strip=True)
                match = re.search(r"\b" + name.replace("-", "[ -]") + r"\s*:\s*([^\n]+)", text, re.I)
                if match:
                    return match[1].strip()
            return ""
        company = field(["company", "company-name"])
        location = field(["location", "job-location"])
        if not location:
            location = next((line.strip() for line in text.splitlines() if INDIA.search(line) or COUNTRIES.search(line)), "Not specified")
        exp = field(["experience"])
        posted = field(["posted", "date-posted"])
        basis = "Source posting date"
        if not stamp(posted) and date_policy == "alert_received":
            posted, basis = received.isoformat(), "Alert received; posting date NOT verified"
        jobs.append(make_job(title, company, location, platform + " email", anchor["href"], posted, text, experience=exp, date_basis=basis))
    return jobs


def gmail_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    value = os.getenv("GMAIL_TOKEN_JSON") or (ROOT / "token.json").read_text(encoding="utf-8")
    credentials = Credentials.from_authorized_user_info(json.loads(value), ["https://www.googleapis.com/auth/gmail.modify"])
    if not credentials.valid:
        credentials.refresh(Request())
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def message_body(payload, service, message_id):
    bodies = []
    def walk(part):
        body = part.get("body", {})
        data = body.get("data")
        if not data and body.get("attachmentId") and part.get("mimeType") in {"text/html", "text/plain"}:
            data = service.users().messages().attachments().get(userId="me", messageId=message_id, id=body["attachmentId"]).execute().get("data")
        if data and part.get("mimeType") in {"text/html", "text/plain"}:
            bodies.append((part.get("mimeType"), base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")))
        for child in part.get("parts", []):
            walk(child)
    walk(payload)
    return "\n".join(text for kind, text in bodies if kind == "text/html") or "\n".join(text for _, text in bodies)


def gmail(config, state, now):
    if os.getenv("GMAIL_ENABLED", "true").lower() != "true":
        return [], [], None, ["Gmail alert parsing disabled"]
    service = gmail_service()
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    label = next((x["id"] for x in labels if x["name"] == config["gmail_label"]), None)
    if not label:
        raise ValueError("Create JobAlerts label first")
    jobs, ids, warnings, page = [], [], [], None
    while True:
        data = service.users().messages().list(userId="me", labelIds=[label, "UNREAD"], maxResults=100, pageToken=page).execute()
        for item in data.get("messages", []):
            if message_key(item["id"]) in state.get("processed_messages", []):
                ids.append(item["id"])
                continue
            msg = service.users().messages().get(userId="me", id=item["id"], format="full").execute()
            sender = next((h["value"] for h in msg["payload"].get("headers", []) if h["name"].lower() == "from"), "")
            received = stamp(int(msg["internalDate"]))
            rows = parse_alert(message_body(msg["payload"], service, msg["id"]), sender, received, os.getenv("DATE_POLICY", "strict"))
            if not rows:
                warnings.append(f"{next((p for p in ['LinkedIn','Naukri','Foundit','Instahyre'] if p.lower() in sender.lower()), 'Gmail')}: an alert had no recognized job cards; left unread for review")
                continue
            unknown = sum(not j.posted for j in rows)
            if unknown:
                warnings.append(f"Gmail: {unknown} job(s) lack a verifiable posting date; held out in strict mode, alert left unread")
            jobs.extend(rows)
            if not unknown:
                ids.append(item["id"])
        page = data.get("nextPageToken")
        if not page:
            break
    return jobs, ids, service, list(dict.fromkeys(warnings))


def mark_processed(service, ids, config):
    if not service or not ids:
        return
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    label = next((x["id"] for x in labels if x["name"] == config["gmail_processed_label"]), None)
    if not label:
        label = service.users().labels().create(userId="me", body={"name": config["gmail_processed_label"]}).execute()["id"]
    for start in range(0, len(ids), 1000):
        service.users().messages().batchModify(userId="me", body={"ids": ids[start:start+1000], "removeLabelIds": ["UNREAD"], "addLabelIds": [label]}).execute()


def digest(jobs, warnings, now):
    esc = lambda x: html.escape(str(x), quote=True)
    sections = []
    for heading, india in [("India", True), ("Outside India / Remote", False)]:
        cards = []
        for j in jobs:
            if bool(INDIA.search(j.location)) != india:
                continue
            date = stamp(j.posted).astimezone(IST).strftime("%d %b %Y %H:%M IST")
            cards.append(f'<article style="border-bottom:1px solid #ddd;padding:16px 0"><h3>{esc(j.title)}</h3><p><b>Company:</b> {esc(j.company)}<br><b>Location:</b> {esc(j.location)} ({esc(j.mode)})<br><b>Experience:</b> {esc(j.experience)}<br><b>Source:</b> {esc(j.source)}<br><b>Posted/date:</b> {date} — {esc(j.date_basis)}</p><p>{esc(j.description[:450])}</p><p><a href="{esc(j.url)}">Apply / original source listing</a></p></article>')
        sections.append(f"<h2>{heading}</h2>" + ("".join(cards) or "<p>No new matches.</p>"))
    heading = f"{len(jobs)} new job matches" if jobs else "No new jobs today"
    if warnings and not jobs:
        heading = "No new matches from available sources — coverage incomplete"
    warning_html = "<h2>Source status / limitations</h2><ul>" + "".join(f"<li>{esc(w)}</li>" for w in warnings) + "</ul>" if warnings else ""
    return f'<!doctype html><html><body style="font-family:Arial;max-width:800px;margin:auto"><h1>{heading}</h1><p>{now.astimezone(IST):%d %b %Y} · Last 24 hours · Check location restrictions and work authorization before applying.</p>{"".join(sections)}{warning_html}</body></html>'


def send(body, count, warnings):
    msg = EmailMessage()
    msg["From"] = os.environ["GMAIL_USER"]
    msg["To"] = os.environ.get("EMAIL_TO") or os.environ["GMAIL_USER"]
    msg["Subject"] = f"DevOps job alert: {count} new matches" if count else "No new jobs today" if not warnings else "Job alert: no new matches; coverage incomplete"
    msg.set_content(plain(body))
    msg.add_alternative(body, subtype="html")
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=40) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"].replace(" ", ""))
        smtp.send_message(msg)


def run(args):
    load_dotenv(ROOT / ".env")
    now = datetime.now(UTC)
    config = json.loads((ROOT / "config.json").read_text())
    state = json.loads((ROOT / "data/state.json").read_text())
    warnings, jobs, message_ids, service = [], [], [], None
    if args.demo:
        jobs = [make_job("Junior DevOps Engineer", "Example company (demo)", "Bengaluru, India", "Demo", "https://example.com/jobs/demo", now.isoformat(), "AWS, Terraform, Kubernetes. 1-3 years experience."), make_job("Cloud Engineer II", "Example remote company (demo)", "Worldwide", "Demo", "https://example.com/jobs/remote", now.isoformat(), "Cloud infrastructure and CI/CD", mode="Remote")]
    else:
        for name, fetch in [("Remotive", remotive), ("Remote OK", remoteok), ("Himalayas", himalayas), ("We Work Remotely", wwr), ("Adzuna", adzuna)]:
            try:
                result = fetch(config, state, now)
                rows, notices = result if isinstance(result, tuple) else (result, [])
                jobs.extend(rows)
                warnings.extend(notices)
                logging.info("%s: %d records", name, len(rows))
            except Exception as error:
                # Do not log request URLs: some contain API keys.
                warnings.append(f"{name} failed ({type(error).__name__}); inspect configuration and provider status")
        rows, notices = jsearch(config, state, now)
        jobs.extend(rows)
        warnings.extend(notices)
        try:
            rows, message_ids, service, notices = gmail(config, state, now)
            jobs.extend(rows)
            warnings.extend(notices)
        except Exception as error:
            warnings.append(f"Gmail failed ({type(error).__name__}); check OAuth token and label")
    selected, batch = [], set()
    for job in jobs:
        if eligible(job, now) and not any(key in state["seen"] or key in batch for key in job.ids()):
            selected.append(job)
            batch.update(job.ids())
    warnings = list(dict.fromkeys(warnings))
    body = digest(selected, warnings, now)
    (ROOT / "preview.html").write_text(body, encoding="utf-8")
    logging.info("%d new jobs; %d source notices. Preview: preview.html", len(selected), len(warnings))
    if args.dry_run or args.demo:
        return
    send(body, len(selected), warnings)
    # Only record delivery after SMTP accepts the digest.
    for key in batch:
        state["seen"][key] = now.isoformat()
    state["processed_messages"] = list(set(state.get("processed_messages", [])) | {message_key(mid) for mid in message_ids})
    save_state(state)
    mark_processed(service, message_ids, config)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Fetch and preview without SMTP or Gmail label changes; API budget reservations still persist")
    parser.add_argument("--demo", action="store_true", help="Offline sample digest; never sends or changes state")
    run(parser.parse_args())
