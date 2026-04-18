"""ZHS connector — Ory Kratos + TUM SSO login, GraphQL sport search, and registration.

Login flow:
  1. Navigate to /auth/login on kurse.zhs-muenchen.de
  2. Click "Login mit Universitätsaccount" dropdown → select TUM
  3. TUM OIDC redirect → login.tum.de j_username/j_password
  4. OIDC attribute-release consent page → proceed
  5. Back on kurse.zhs-muenchen.de logged in

Search flow:
  - POST /api/query (GraphQL, cookie-authenticated) with query { offers { id name description slug } }
  - Client-side filter by keyword (no server-side search arg available)
  - 324 live offers returned

Registration flow:
  - Navigate to /de/kurse/{slug}
  - Click "Register" / "Zum Warenkorb" button
  - Confirm on modal if present
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

_ZHS_BASE = "https://kurse.zhs-muenchen.de"
_ZHS_GQL = f"{_ZHS_BASE}/api/query"

_OFFERS_QUERY = "{ offers { id name description slug } }"


@dataclass
class SportSlot:
    """A single bookable ZHS sport slot."""
    id: str
    title: str
    sport: str
    day: str
    time: str
    location: str
    spots_left: int
    url: str


class ZHSConnector:
    """Playwright-based connector for kurse.zhs-muenchen.de."""

    def __init__(self) -> None:
        self._bearer_token: Optional[str] = None

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    def login(self, page, username: str, password: str) -> bool:
        """Log in to ZHS via TUM SSO (Ory Kratos → OIDC → login.tum.de → consent).

        Returns True when back on kurse.zhs-muenchen.de logged in.
        """
        # Navigate directly to the ZHS login page
        page.goto(
            f"{_ZHS_BASE}/auth/login?return_to={_ZHS_BASE}/de",
            timeout=30_000,
        )
        page.wait_for_load_state("networkidle", timeout=20_000)

        # Click "Login mit Universitätsaccount" dropdown trigger
        page.click('[data-melt-dropdown-menu-trigger]')
        page.wait_for_timeout(1_000)

        # Select TUM from dropdown
        page.locator('[role="menuitem"]:has-text("TUM")').first.click()
        page.wait_for_load_state("networkidle", timeout=20_000)

        # Fill TUM IdP credentials
        if "login.tum.de" in page.url:
            page.fill('input[name="j_username"]', username)
            page.fill('input[name="j_password"]', password)
            page.click('button[type="submit"]')
            page.wait_for_load_state("networkidle", timeout=20_000)

        # Handle OIDC attribute-release consent screen (first-time only)
        if "idp" in page.url and page.locator('input[name="_eventId_proceed"]').count() > 0:
            page.click('input[name="_eventId_proceed"]')
            page.wait_for_load_state("networkidle", timeout=20_000)

        return "kurse.zhs-muenchen.de" in page.url

    def _get_session(self, page) -> requests.Session:
        """Build a requests.Session with ZHS cookies from the Playwright context."""
        sess = requests.Session()
        for ck in page.context.cookies():
            if "zhs" in ck.get("domain", "") or "kurse" in ck.get("domain", ""):
                sess.cookies.set(ck["name"], ck["value"], domain="kurse.zhs-muenchen.de")
        return sess

    # ------------------------------------------------------------------
    # Search via GraphQL (cookie-authenticated, no bearer token needed)
    # ------------------------------------------------------------------

    def search_sports(self, page, query: str, limit: int = 20) -> list[SportSlot]:
        """Fetch all ZHS offers via GraphQL and filter by keyword client-side."""
        try:
            sess = self._get_session(page)
            resp = sess.post(_ZHS_GQL, json={"query": _OFFERS_QUERY}, timeout=15)
            resp.raise_for_status()
            all_offers = resp.json().get("data", {}).get("offers", [])

            q = query.lower()
            matched = [
                o for o in all_offers
                if q in (o.get("name") or "").lower()
                or q in (o.get("description") or "").lower()
            ]
            return [self._offer_to_slot(o) for o in matched[:limit]]
        except Exception as exc:
            print(f"[ZHSConnector] GraphQL search failed: {exc}")
            return []

    def _offer_to_slot(self, offer: dict) -> SportSlot:
        """Parse a raw GraphQL offer into a SportSlot."""
        desc_html = offer.get("description") or ""
        soup = BeautifulSoup(desc_html, "html.parser")
        desc_text = soup.get_text(" ", strip=True)

        # Extract location: often in first italic tag or after "Ort:"
        location = ""
        em = soup.find("em")
        if em:
            parts = em.get_text(" ", strip=True).split(" - ")
            location = parts[-1] if parts else ""

        # Extract day/time pattern: "Mo 08:00 - 09:30"
        time_match = re.search(r"(Mo|Di|Mi|Do|Fr|Sa|So)\s+(\d{2}:\d{2})\s*[-–]\s*(\d{2}:\d{2})", desc_text)
        day = time_match.group(1) if time_match else ""
        time_str = f"{time_match.group(2)}–{time_match.group(3)}" if time_match else ""

        slug = offer.get("slug", "")

        # Calculate spots from capacity fields if available
        max_p = offer.get("maxParticipants")
        cur_p = offer.get("currentParticipants")
        if max_p is not None and cur_p is not None:
            try:
                spots = int(max_p) - int(cur_p)
                spots_left = max(0, spots)
            except (TypeError, ValueError):
                spots_left = 0
        else:
            # Try parsing from description HTML as fallback
            # ZHS sometimes shows "X freie Plätze" or "X/Y" in description
            spots_left = 0  # default to 0 if no availability info found
            free_match = re.search(
                r"(\d+)\s*(?:freie?\s*Pl[äa]tze?|free\s*spots?|available)",
                desc_text,
                re.IGNORECASE,
            )
            if free_match:
                try:
                    spots_left = int(free_match.group(1))
                except ValueError:
                    spots_left = 0
            else:
                # Try "X/Y" pattern (booked/total)
                ratio_match = re.search(r"(\d+)\s*/\s*(\d+)", desc_text)
                if ratio_match:
                    try:
                        booked = int(ratio_match.group(1))
                        total = int(ratio_match.group(2))
                        spots_left = max(0, total - booked)
                    except ValueError:
                        spots_left = 0

        return SportSlot(
            id=offer["id"],
            title=offer["name"],
            sport=offer["name"].split(" - ")[0],
            day=day,
            time=time_str,
            location=location,
            spots_left=spots_left,
            url=f"{_ZHS_BASE}/de/kurse/{slug}",
        )

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, page, slot: SportSlot) -> dict:
        """Attempt to register for a sport slot.

        Returns a dict with keys: success (bool), message (str), screenshot (bytes|None).
        """
        try:
            page.goto(slot.url, timeout=20_000)
            page.wait_for_load_state("networkidle", timeout=15_000)

            # Look for registration/booking button
            btn = page.locator(
                'button:has-text("Register"), button:has-text("Anmelden"), '
                'button:has-text("Registrieren"), a:has-text("Register"), '
                '[class*="book"], [class*="register"]'
            ).first

            if not btn.is_visible(timeout=5_000):
                screenshot = page.screenshot()
                return {
                    "success": False,
                    "message": "No registration button found — course may be full or require additional steps.",
                    "screenshot": screenshot,
                }

            btn.click()
            page.wait_for_load_state("networkidle", timeout=10_000)

            # Handle confirmation modal if present
            confirm = page.locator(
                'button:has-text("Bestätigen"), button:has-text("Confirm"), '
                'button:has-text("Ja"), button[type="submit"]'
            ).first
            if confirm.is_visible(timeout=3_000):
                confirm.click()
                page.wait_for_load_state("networkidle", timeout=10_000)

            screenshot = page.screenshot()
            page_text = page.inner_text("body")

            success_indicators = ["erfolgreich", "success", "gebucht", "angemeldet", "bestätigt"]
            error_indicators = ["fehler", "error", "nicht möglich", "bereits", "voll"]

            if any(ind in page_text.lower() for ind in success_indicators):
                return {"success": True, "message": f"Successfully registered for {slot.title}!", "screenshot": screenshot}
            if any(ind in page_text.lower() for ind in error_indicators):
                return {"success": False, "message": f"Registration failed: {page_text[:200]}", "screenshot": screenshot}

            return {"success": True, "message": f"Registration submitted for {slot.title}. Check your TUM email for confirmation.", "screenshot": screenshot}

        except Exception as exc:
            return {"success": False, "message": f"Registration error: {exc}", "screenshot": None}

    # ------------------------------------------------------------------
    # Full workflow
    # ------------------------------------------------------------------

    def run(self, username: str, password: str, query: str, register_first: bool = False) -> dict:
        """Full flow: login → search → optionally register for first result.

        Returns dict with: logged_in, slots, registered, message.
        """
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                logged_in = self.login(page, username, password)
                if not logged_in:
                    return {
                        "logged_in": False,
                        "slots": [],
                        "registered": None,
                        "message": "ZHS login failed — check credentials.",
                    }

                slots = self.search_sports(page, query)
                registered = None
                message = f"Found {len(slots)} course(s) for '{query}'."

                if register_first and slots:
                    registered = self.register(page, slots[0])
                    message = registered["message"]

                return {
                    "logged_in": True,
                    "slots": slots,
                    "registered": registered,
                    "message": message,
                }
            except Exception as exc:
                return {
                    "logged_in": False,
                    "slots": [],
                    "registered": None,
                    "message": f"ZHS error: {exc}",
                }
            finally:
                browser.close()
