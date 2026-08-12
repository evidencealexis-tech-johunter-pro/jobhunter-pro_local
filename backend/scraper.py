"""
Job scraping module — RemoteOK (official public JSON API) and
We Work Remotely (official public RSS feeds).

Both sources are used with their sanctioned public endpoints, no
HTML scraping, no auth, no proxies needed.
"""

import re
import requests
import xml.etree.ElementTree as ET
import hashlib

HEADERS = {"User-Agent": "JobHunterProBot/1.0 (personal job search tool)"}


def normalize_job(title, company, location, url, posted_date, is_remote, description, source):
    """Map any source's raw job data into one standard schema."""
    canonical = (url or f"{company}-{title}").strip().lower()
    dedup_hash = hashlib.sha256(canonical.encode()).hexdigest()
    return {
        "title": (title or "Untitled").strip(),
        "company": (company or "Unknown").strip(),
        "location": location or ("Remote" if is_remote else ""),
        "url": url or "",
        "posted_date": posted_date or "",
        "is_remote": is_remote,
        "description": description or "",
        "source": source,
        "dedup_hash": dedup_hash,
    }


def humanize_fetch_error(exc):
    """
    Turns a raw Requests/network exception into a short, plain-English
    message a non-technical user can actually understand. This is the
    ONLY place fetch-related error text gets generated - every failure
    path in detect_and_fetch() routes through here, so the message the
    user sees is always consistent, never a raw Python traceback.
    """
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "This site took too long to connect. It may be temporarily down."
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return "This site started responding but was too slow to finish. It may be overloaded right now."
    if isinstance(exc, requests.exceptions.Timeout):
        return "This site took too long to respond."
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "Couldn't connect to this site. Please check the web address or try again later."
    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        if status == 403:
            return "This site is blocking automated access. Try a different job source."
        if status == 404:
            return "This page couldn't be found. Please double-check the web address."
        if status == 429:
            return "This site is limiting how often it can be checked right now. Try again in a little while."
        if status and status >= 500:
            return "This site is having server issues right now. Try again later."
        return "This site returned an error and couldn't be read."
    if isinstance(exc, (requests.exceptions.MissingSchema, requests.exceptions.InvalidURL)):
        return "That doesn't look like a valid web address. Please check it and try again."
    if isinstance(exc, ET.ParseError):
        return "This site's job feed couldn't be read - the format may have changed."
    return "Something went wrong trying to reach this site. Please try again later."


def fetch_remoteok_jobs(tag=None, limit=200):
    """Fetch jobs from RemoteOK's official public JSON API."""
    resp = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    # RemoteOK's first array item is a legal/metadata notice, not a job - skip it
    jobs = [item for item in data if isinstance(item, dict) and item.get("id")]

    normalized = []
    for job in jobs:
        if tag:
            tags = [t.lower() for t in job.get("tags", [])]
            if tag.lower() not in tags:
                continue
        normalized.append(normalize_job(
            title=job.get("position"),
            company=job.get("company"),
            location=job.get("location"),
            url=job.get("url") or f"https://remoteok.com{job.get('slug', '')}",
            posted_date=job.get("date"),
            is_remote=True,
            description=job.get("description"),
            source="RemoteOK",
        ))
        if len(normalized) >= limit:
            break
    return normalized


WWR_CATEGORY_FEEDS = {
    "all": "https://weworkremotely.com/remote-jobs.rss",
    "programming": "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "devops": "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "design": "https://weworkremotely.com/categories/remote-design-jobs.rss",
    "product": "https://weworkremotely.com/categories/remote-product-jobs.rss",
    "customer-support": "https://weworkremotely.com/categories/remote-customer-support-jobs.rss",
    "sales-marketing": "https://weworkremotely.com/categories/remote-sales-and-marketing-jobs.rss",
}


def fetch_wwr_jobs(category="all", limit=200):
    """
    Fetch jobs from We Work Remotely's official public RSS feeds.

    IMPORTANT: unlike RemoteOK/Greenhouse/Lever, WWR's RSS feeds ARE
    genuinely capped by the provider itself - there's no true pagination
    available for RSS. To get real additional coverage (not just raise a
    number we control), this combines ALL of WWR's category feeds and
    deduplicates by URL, since each category feed can independently
    contain postings the single "all" feed's own cap left out.
    """
    if category != "all":
        feed_url = WWR_CATEGORY_FEEDS.get(category, WWR_CATEGORY_FEEDS["all"])
        return _fetch_one_wwr_feed(feed_url, limit)

    seen_urls = set()
    combined = []
    for feed_url in WWR_CATEGORY_FEEDS.values():
        try:
            jobs = _fetch_one_wwr_feed(feed_url, limit)
        except Exception:
            continue  # one category feed being down shouldn't kill the rest
        for job in jobs:
            if job["url"] and job["url"] not in seen_urls:
                seen_urls.add(job["url"])
                combined.append(job)
        if len(combined) >= limit:
            break
    return combined[:limit]


def _fetch_one_wwr_feed(feed_url, limit):
    resp = requests.get(feed_url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    normalized = []
    for item in root.findall(".//item"):
        title_raw = (item.findtext("title") or "").strip()
        if ":" in title_raw:
            company, _, title = title_raw.partition(":")
        else:
            company, title = "", title_raw

        normalized.append(normalize_job(
            title=title.strip() or title_raw,
            company=company.strip(),
            location="Remote",
            url=(item.findtext("link") or "").strip(),
            posted_date=(item.findtext("pubDate") or "").strip(),
            is_remote=True,
            description=(item.findtext("description") or "").strip(),
            source="We Work Remotely",
        ))
        if len(normalized) >= limit:
            break
    return normalized


def fetch_greenhouse_jobs(company_slug, limit=300):
    """Fetch jobs from a company's Greenhouse job board via its public JSON API."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs?content=true"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    normalized = []
    for job in data.get("jobs", []):
        location = (job.get("location") or {}).get("name", "")
        normalized.append(normalize_job(
            title=job.get("title"),
            company=company_slug,
            location=location,
            url=job.get("absolute_url"),
            posted_date=job.get("updated_at"),
            is_remote="remote" in location.lower(),
            description=job.get("content"),
            source="Greenhouse",
        ))
        if len(normalized) >= limit:
            break
    return normalized


def fetch_lever_jobs(company_slug, limit=300):
    """Fetch jobs from a company's Lever job board via its public JSON API."""
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    normalized = []
    for job in data:
        location = (job.get("categories") or {}).get("location", "") or ""
        normalized.append(normalize_job(
            title=job.get("text"),
            company=company_slug,
            location=location,
            url=job.get("hostedUrl"),
            posted_date=job.get("createdAt"),
            is_remote="remote" in location.lower(),
            description=job.get("descriptionPlain") or job.get("description") or "",
            source="Lever",
        ))
        if len(normalized) >= limit:
            break
    return normalized


def fetch_generic_html(url, max_chars=15000):
    """Fetch raw HTML for any URL not matching a known API-backed source."""
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text[:max_chars]


def detect_and_fetch(url):
    """
    Given whatever URL the user typed into Settings, figure out which
    known source it matches and fetch it. Returns (status, data):
      - ("ok", [normalized_jobs])   for RemoteOK/WWR/Greenhouse/Lever
      - ("generic", raw_html)       for any other URL - extraction happens
                                     in main.py via the LLM, so this stays
                                     a plain fetch, no domain allowlist
      - ("error", message)          if the URL couldn't be reached at all -
                                     message is always plain English, see
                                     humanize_fetch_error() above

    IMPORTANT: this whole function is wrapped in ONE try/except, on
    purpose - every branch below (RemoteOK, WWR, Greenhouse, Lever, and
    the generic fallback) shares the same error handling, so no matter
    which source fails, the user always gets a clean, readable message
    instead of a raw exception leaking through uncaught.
    """
    try:
        if "remoteok.com" in url:
            return "ok", fetch_remoteok_jobs()

        if "weworkremotely.com" in url:
            return "ok", fetch_wwr_jobs(category="all")

        m = re.search(r"boards\.greenhouse\.io/([^/?#]+)", url)
        if m:
            return "ok", fetch_greenhouse_jobs(m.group(1))

        m = re.search(r"jobs\.lever\.co/([^/?#]+)", url)
        if m:
            return "ok", fetch_lever_jobs(m.group(1))

        html = fetch_generic_html(url)
        return "generic", html

    except Exception as e:
        return "error", humanize_fetch_error(e)