"""
TenderIQ Scraper Engine
=======================
Scheduled scrapers for PPRA (Kenya), AGPO portal, county portals, and UN portals.
Each scraper is a class that implements a `scrape()` method returning a list of
normalised tender dicts.

The runner is called by the Frappe scheduler every 6 hours.
"""
import frappe
import requests
from bs4 import BeautifulSoup
from frappe.utils import now_datetime, add_days, nowdate
import re


# ---------------------------------------------------------------------------
# Scraper Base
# ---------------------------------------------------------------------------

class BaseScraper:
    source_name = "Unknown"
    base_url = ""
    timeout = 20

    def scrape(self):
        """Return list of dicts: {tender_number, tender_name, procuring_entity,
        deadline, source, category, url, description}"""
        raise NotImplementedError

    def _get(self, url, **kwargs):
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; TenderIQ/1.0; "
                "+https://github.com/tenderiq)"
            )
        }
        resp = requests.get(url, headers=headers, timeout=self.timeout, **kwargs)
        resp.raise_for_status()
        return resp

    def _soup(self, url, **kwargs):
        return BeautifulSoup(self._get(url, **kwargs).text, "html.parser")


# ---------------------------------------------------------------------------
# PPRA Kenya Scraper
# ---------------------------------------------------------------------------

class PPRAScraper(BaseScraper):
    """
    Scrapes the Kenya PPRA tender portal at ppra.go.ke.
    The portal uses a paginated table at /tenders.
    """
    source_name = "PPRA"
    base_url = "https://ppra.go.ke"
    tenders_path = "/tenders"

    def scrape(self):
        results = []
        try:
            page = 1
            while page <= 5:  # max 5 pages per run to avoid hammering
                url = f"{self.base_url}{self.tenders_path}?page={page}"
                soup = self._soup(url)

                # PPRA uses a table with class 'table' for tender listings
                rows = soup.select("table.table tbody tr")
                if not rows:
                    break

                for row in rows:
                    cols = row.find_all("td")
                    if len(cols) < 4:
                        continue
                    try:
                        tender = {
                            "tender_number": cols[0].get_text(strip=True),
                            "tender_name": cols[1].get_text(strip=True),
                            "procuring_entity": cols[2].get_text(strip=True),
                            "deadline": _parse_date(cols[3].get_text(strip=True)),
                            "source": "PPRA",
                            "category": _infer_category(cols[1].get_text(strip=True)),
                            "url": self.base_url + (cols[1].find("a") or {}).get("href", ""),
                            "description": "",
                        }
                        results.append(tender)
                    except Exception:
                        continue

                # Stop if no next page link
                if not soup.find("a", string=re.compile(r"Next|>")):
                    break
                page += 1

        except requests.RequestException as exc:
            frappe.log_error(
                f"PPRA scraper error: {exc}", "TenderIQ Scraper"
            )

        return results


# ---------------------------------------------------------------------------
# AGPO Portal Scraper
# ---------------------------------------------------------------------------

class AGPOScraper(BaseScraper):
    """
    Scrapes AGPO (Access to Government Procurement Opportunities) portal.
    Targets youth/women/PWD set-aside tenders.
    """
    source_name = "AGPO"
    base_url = "https://agpo.go.ke"
    tenders_path = "/tenders"

    def scrape(self):
        results = []
        try:
            soup = self._soup(f"{self.base_url}{self.tenders_path}")
            # AGPO portal structure — adapt selectors as needed
            cards = soup.select(".tender-card, .tender-item, article.tender")
            for card in cards:
                name_el = card.find(class_=re.compile(r"title|name", re.I))
                entity_el = card.find(class_=re.compile(r"entity|ministry|org", re.I))
                deadline_el = card.find(class_=re.compile(r"deadline|closing|date", re.I))
                results.append({
                    "tender_name": name_el.get_text(strip=True) if name_el else "Unknown",
                    "procuring_entity": entity_el.get_text(strip=True) if entity_el else "",
                    "deadline": _parse_date(deadline_el.get_text(strip=True)) if deadline_el else None,
                    "source": "AGPO",
                    "category": "Goods",
                    "tender_number": "",
                    "url": self.base_url + self.tenders_path,
                    "description": "",
                })
        except requests.RequestException as exc:
            frappe.log_error(f"AGPO scraper error: {exc}", "TenderIQ Scraper")
        return results


# ---------------------------------------------------------------------------
# UN Global Marketplace Scraper (Public RSS)
# ---------------------------------------------------------------------------

class UNGMScraper(BaseScraper):
    """
    Scrapes the UN Global Marketplace (UNGM) public RSS feed for tenders
    relevant to East Africa.
    """
    source_name = "UNGM"
    rss_url = "https://www.ungm.org/Public/Notice/SearchNotices?publishedFrom=&publishedTo=&deadline=&noticeType=0&title=&description=&tenderSymbol=&countries=KE,TZ,UG,RW&agencies=0&pageIndex=0&pageSize=20&format=rss"

    def scrape(self):
        results = []
        try:
            resp = self._get(self.rss_url)
            soup = BeautifulSoup(resp.content, "xml")
            items = soup.find_all("item")
            for item in items:
                title = item.find("title")
                link = item.find("link")
                pub_date = item.find("pubDate")
                description = item.find("description")
                results.append({
                    "tender_name": title.get_text(strip=True) if title else "Unknown",
                    "procuring_entity": "UN Agency",
                    "deadline": None,
                    "source": "UNGM",
                    "category": _infer_category(title.get_text(strip=True) if title else ""),
                    "tender_number": "",
                    "url": link.get_text(strip=True) if link else "",
                    "description": _strip_html(description.get_text() if description else "")[:500],
                })
        except Exception as exc:
            frappe.log_error(f"UNGM scraper error: {exc}", "TenderIQ Scraper")
        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(raw):
    """Try to parse a date string into YYYY-MM-DD."""
    import dateutil.parser
    try:
        return dateutil.parser.parse(raw, dayfirst=True).strftime("%Y-%m-%d")
    except Exception:
        return None


def _infer_category(text):
    """Heuristically infer tender category from title."""
    text_lower = text.lower()
    if any(w in text_lower for w in ["consult", "advisory", "study", "assessment", "survey"]):
        return "Consultancy"
    if any(w in text_lower for w in ["construct", "civil", "road", "build", "works", "infrastructure"]):
        return "Works"
    if any(w in text_lower for w in ["supply", "goods", "equipment", "vehicle", "furniture", "purchase"]):
        return "Goods"
    return "Services"


def _strip_html(html_text):
    """Remove HTML tags."""
    return BeautifulSoup(html_text, "html.parser").get_text(separator=" ")


# ---------------------------------------------------------------------------
# Keyword Matching
# ---------------------------------------------------------------------------

def _matches_keywords(tender_dict, keywords):
    """Return True if tender name/description matches any keyword."""
    if not keywords:
        return True  # no filter = match all
    text = f"{tender_dict.get('tender_name','')} {tender_dict.get('description','')}".lower()
    for kw in keywords:
        if kw.lower().strip() in text:
            return True
    return False


# ---------------------------------------------------------------------------
# Runner — called by Frappe scheduler
# ---------------------------------------------------------------------------

def run_all_scrapers():
    """
    Entry point called by hooks.py scheduler every 6 hours.
    Runs all scrapers, filters against configured keywords,
    and creates Tender records for new opportunities.
    """
    settings = frappe.get_single("TenderIQ Settings")
    raw_keywords = getattr(settings, "watch_keywords", "") or ""
    keywords = [k.strip() for k in raw_keywords.splitlines() if k.strip()]

    scrapers = [PPRAScraper(), AGPOScraper(), UNGMScraper()]
    total_new = 0

    for scraper in scrapers:
        try:
            tenders = scraper.scrape()
        except Exception as exc:
            frappe.log_error(
                f"{scraper.source_name} scraper failed: {exc}",
                "TenderIQ Scraper",
            )
            continue

        for t in tenders:
            if not _matches_keywords(t, keywords):
                continue
            if _tender_already_exists(t):
                continue

            try:
                _create_tender_from_scrape(t)
                total_new += 1
            except Exception as exc:
                frappe.log_error(
                    f"Failed to create tender from scrape: {exc} | {t}",
                    "TenderIQ Scraper",
                )

    frappe.logger("tenderiq").info(
        f"Scraper run complete. {total_new} new tenders created."
    )


def _tender_already_exists(t):
    """Check if we already have this tender by number or name+entity."""
    if t.get("tender_number"):
        if frappe.db.exists("Tender", {"tender_number": t["tender_number"]}):
            return True
    if t.get("tender_name") and t.get("procuring_entity"):
        if frappe.db.exists(
            "Tender",
            {
                "tender_name": t["tender_name"],
                "procuring_entity": t["procuring_entity"],
            },
        ):
            return True
    return False


def _create_tender_from_scrape(t):
    """Create a new Tender record from scraped data."""
    tender = frappe.new_doc("Tender")
    tender.tender_number = t.get("tender_number") or ""
    tender.tender_name = t.get("tender_name") or "Untitled Tender"
    tender.procuring_entity = t.get("procuring_entity") or ""
    tender.category = t.get("category") or "Services"
    tender.source = t.get("source") or "Other"
    tender.status = "Identified"
    tender.description = (
        f"Auto-discovered from {t.get('source','')} scraper.\n"
        f"Source URL: {t.get('url','')}\n\n"
        f"{t.get('description','')}"
    )
    if t.get("deadline"):
        tender.deadline = t["deadline"]
    tender.insert(ignore_permissions=True)
    frappe.db.commit()

    # Notify Bid Managers about new tender
    _notify_bid_managers(tender)


def _notify_bid_managers(tender):
    """Send email notification to users with Bid Manager role."""
    try:
        bid_managers = frappe.get_all(
            "Has Role",
            filters={"role": "Bid Manager"},
            fields=["parent"],
        )
        recipients = [r.parent for r in bid_managers if frappe.db.exists("User", r.parent)]
        if not recipients:
            return

        frappe.sendmail(
            recipients=recipients,
            subject=f"[TenderIQ] New Tender Identified: {tender.tender_name}",
            message=f"""
            <p>A new tender has been automatically identified:</p>
            <ul>
                <li><strong>Tender:</strong> {tender.tender_name}</li>
                <li><strong>Entity:</strong> {tender.procuring_entity}</li>
                <li><strong>Category:</strong> {tender.category}</li>
                <li><strong>Source:</strong> {tender.source}</li>
                <li><strong>Deadline:</strong> {tender.deadline or 'Not specified'}</li>
            </ul>
            <p><a href="/app/tender/{tender.name}">View in TenderIQ</a></p>
            """,
        )
    except Exception as exc:
        frappe.log_error(f"Notification error: {exc}", "TenderIQ Scraper")
