"""TUMonline connector — Keycloak → Shibboleth login + deadline scraping."""

import json
import re
from datetime import datetime
from typing import Optional

_TUMONLINE_BASE = "https://campus.tum.de/tumonline"

_GERMAN_MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8,
    "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}


def parse_date(text: str) -> Optional[str]:
    """Extract YYYY-MM-DD from German or ISO date strings."""
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    if m:
        try:
            return datetime.strptime(m.group(0), "%d.%m.%Y").strftime("%Y-%m-%d")
        except ValueError:
            pass
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return m.group(0)
    m = re.search(
        r"(\d{1,2})\.\s*(" + "|".join(_GERMAN_MONTHS) + r")(?:.*?(\d{4}))?",
        text.lower(),
    )
    if m:
        day = int(m.group(1))
        month = _GERMAN_MONTHS[m.group(2)]
        year = int(m.group(3)) if m.group(3) else datetime.now().year
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


class TUMonlineConnector:
    """Playwright-based connector for campus.tum.de (TUMonline)."""

    BASE = _TUMONLINE_BASE

    def login(self, page, username: str, password: str) -> bool:
        """Two-step TUMonline login: Keycloak username → Shibboleth password.

        Returns True when the post-login page is TUMonline.
        """
        page.goto(self.BASE + "/", timeout=30_000)
        page.wait_for_load_state("networkidle", timeout=20_000)

        # Step 1: Keycloak username-only form
        page.fill('input[name="username"]', username)
        page.click("#kc-login")
        page.wait_for_load_state("networkidle", timeout=20_000)

        # Step 2: Shibboleth password form at login.tum.de
        if "login.tum.de" in page.url:
            page.fill('input[name="j_username"]', username)
            page.fill('input[name="j_password"]', password)
            page.click('button[type="submit"], input[type="submit"]')
            page.wait_for_load_state("networkidle", timeout=20_000)

        return "campus.tum.de" in page.url

    def get_deadlines(self, page) -> list[dict]:
        """Scrape wbEeHooks.showHooks for upcoming deadline items."""
        page.goto(self.BASE + "/wbEeHooks.showHooks", timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=15_000)

        deadlines: list[dict] = []
        today = datetime.now()

        for el in page.locator("li, tr, .hook-item, p").all():
            text = el.inner_text().strip()
            if not text or len(text) < 10:
                continue
            date_str = parse_date(text)
            if not date_str:
                continue
            if datetime.strptime(date_str, "%Y-%m-%d") < today:
                continue
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            deadlines.append({
                "title": lines[0][:100],
                "course": lines[1][:80] if len(lines) > 1 else "",
                "deadline_date": date_str,
                "source": "tumonline",
            })

        return deadlines

    def scrape(self, username: str, password: str) -> list[dict]:
        """Full scrape: launch browser, login, scrape deadlines, close."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                if not self.login(page, username, password):
                    return []
                return self.get_deadlines(page)
            except Exception as exc:
                print(f"[TUMonlineConnector] Error: {exc}")
                return []
            finally:
                browser.close()

    def get_enrolled_courses(self, page) -> dict:
        """Fetch enrolled courses via CAMPUSonline REST API.

        Navigates to the new SPA, forces a Bearer token refresh, then calls
        /slc.tm.cp/student/myCourses for the current semester.

        Returns:
            dict with keys:
              "enrolled": list of str (current semester course names)
              "grades": dict  (empty — grades in student dossier require separate flow)
              "all_courses": list of str (same as enrolled)
        """
        result: dict = {"enrolled": [], "grades": {}, "all_courses": []}

        try:
            # Navigate to SPA to establish auth context
            page.goto(
                "https://campus.tum.de/tumonline/ee/ui/ca2/app/desktop/#/home?$ctx=lang=en",
                timeout=20_000,
            )
            page.wait_for_load_state("networkidle", timeout=15_000)
            page.wait_for_timeout(1000)

            # Force a token refresh via the SPA's own endpoint
            token_data = page.evaluate("""async () => {
                const r = await fetch('/tumonline/ee/rest/auth/token/refresh', {
                    method: 'POST',
                    headers: {Accept: 'application/json', 'Content-Type': 'application/json'},
                    body: '{}'
                });
                return r.ok ? await r.json() : {};
            }""")
            token = token_data.get("accessToken", "")
            if not token:
                print("[TUMonlineConnector] Token refresh returned no accessToken")
                return result

            token_js = json.dumps(token)  # safely quoted for JS string interpolation

            # Step 1: discover current semester ID
            meta = page.evaluate(f"""async () => {{
                const r = await fetch('/tumonline/ee/rest/slc.tm.cp/student/courses?$ctx=lang=EN', {{
                    headers: {{Accept: 'application/json', Authorization: 'Bearer ' + {token_js}}}
                }});
                return r.ok ? await r.json() : {{}};
            }}""")

            semester_id: Optional[int] = None
            for link in meta.get("links", []):
                m = re.search(r'semesterId=(\d+)', link.get("href", ""))
                if m:
                    semester_id = int(m.group(1))
                    break

            if not semester_id:
                print("[TUMonlineConnector] Could not determine semester ID from courses endpoint")
                return result

            # Step 2: fetch enrolled courses for this semester
            data = page.evaluate(f"""async () => {{
                const r = await fetch(
                    '/tumonline/ee/rest/slc.tm.cp/student/myCourses?$filter=termId-eq={semester_id}&$orderBy=title=ascnf&$skip=0&$top=50',
                    {{headers: {{Accept: 'application/json', Authorization: 'Bearer ' + {token_js}}}}}
                );
                return r.ok ? await r.json() : {{}};
            }}""")

            for reg in data.get("registrations", []):
                title = reg.get("course", {}).get("courseTitle", {}).get("value", "")
                if title:
                    result["enrolled"].append(title)

            result["all_courses"] = list(result["enrolled"])
            print(f"[TUMonlineConnector] Found {len(result['enrolled'])} enrolled courses via REST API")

            # Step 3: Fetch grades from achievements endpoint (confirmed working)
            try:
                # Refresh token immediately before achievements fetch
                try:
                    fresh_token_data = page.evaluate("""async () => {
                        const r = await fetch('/tumonline/ee/rest/auth/token/refresh', {
                            method: 'POST',
                            headers: {Accept: 'application/json', 'Content-Type': 'application/json'},
                            body: '{}'
                        });
                        return r.ok ? await r.json() : {};
                    }""")
                    fresh_token = fresh_token_data.get("accessToken", "")
                    if fresh_token:
                        token_js = json.dumps(fresh_token)
                        print("[TUMonlineConnector] Token refreshed before achievements fetch")
                except Exception:
                    pass  # use existing token_js

                achievements_data = page.evaluate(f"""async () => {{
                    const r = await fetch(
                        '/tumonline/ee/rest/slc.xm.ac/achievements?$orderBy=acDate=descnf&$top=200',
                        {{headers: {{Accept: 'application/json', Authorization: 'Bearer ' + {token_js}}}}}
                    );
                    return r.ok ? await r.json() : {{}};
                }}""")

                resources = achievements_data.get("resource", [])
                print(f"[TUMonlineConnector] Achievements endpoint returned {len(resources)} records")

                # Log first non-null gradeDto before parsing loop
                _grade_logged = False
                for resource in resources:
                    dto = resource.get("content", {}).get("achievementDto", {})
                    grade_dto = dto.get("gradeDto")
                    if grade_dto and not _grade_logged:
                        print(f"[TUMonlineConnector] First non-null gradeDto: {json.dumps(grade_dto)}")
                        _grade_logged = True
                        break

                for resource in resources:
                    content = resource.get("content", {})
                    dto = content.get("achievementDto", {})
                    if not dto:
                        continue

                    course_lib = dto.get("cpCourseLibDto", {})
                    course_title_obj = course_lib.get("courseTitle", {})
                    course_name = course_title_obj.get("value")
                    if not course_name or isinstance(course_name, dict):
                        translations = course_title_obj.get("translations", {})
                        trans_list = translations.get("translation", []) if isinstance(translations, dict) else []
                        en_trans = next((t.get("value") for t in trans_list if t.get("lang") == "en"), None)
                        course_name = en_trans or (dto.get("title") or {}).get("value", "")

                    if not course_name or not isinstance(course_name, str):
                        continue
                    course_name = course_name.strip()

                    # Extract grade from gradeDto (confirmed field name from API)
                    grade_dto = dto.get("gradeDto") or {}
                    grade_val = (
                        grade_dto.get("grade") or
                        grade_dto.get("value") or
                        grade_dto.get("gradeValue") or
                        grade_dto.get("key") or
                        grade_dto.get("short")
                    )

                    # Also print gradeDto for first few records to confirm structure
                    if len(result["grades"]) == 0 and grade_dto:
                        print(f"[TUMonlineConnector] gradeDto sample: {json.dumps(grade_dto)[:200]}")

                    if course_name and course_name not in result["all_courses"]:
                        result["all_courses"].append(course_name)

                    if grade_val is not None:
                        try:
                            grade_float = float(str(grade_val).replace(",", "."))
                            if 1.0 <= grade_float <= 5.0:
                                result["grades"][course_name] = grade_float
                        except (ValueError, TypeError):
                            pass

                print(f"[TUMonlineConnector] Parsed {len(result['all_courses'])} completed courses, "
                      f"{len(result['grades'])} with numeric grades")

                if resources:
                    first_dto = resources[0].get("content", {}).get("achievementDto", {})
                    print(f"[TUMonlineConnector] Sample achievement fields: {list(first_dto.keys())}")
                    print(f"[TUMonlineConnector] Sample dto (first 400 chars): {json.dumps(first_dto)[:400]}")

                # Merge: add currently enrolled courses not yet in achievements
                for course in result["enrolled"]:
                    if course not in result["all_courses"]:
                        result["all_courses"].append(course)

                print(f"[TUMonlineConnector] Final: {len(result['all_courses'])} total courses "
                      f"({len(result['enrolled'])} current + historical), "
                      f"{len(result['grades'])} with grades")

            except Exception as exc:
                print(f"[TUMonlineConnector] Achievements fetch failed: {exc}")

        except Exception as exc:
            print(f"[TUMonlineConnector] get_enrolled_courses error: {exc}")

        return result

    def debug_intercept_grade_requests(self, username: str, password: str) -> None:
        """Intercept all XHR/fetch requests made by the TUMonline SPA to find grade endpoints.

        Opens a visible browser, logs in, navigates to the grades section,
        and prints every API request the SPA makes so we can identify the
        correct endpoint and response structure.
        """
        from playwright.sync_api import sync_playwright

        captured_requests: list[dict] = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()

            def handle_request(request):
                url = request.url
                if any(kw in url for kw in [
                    "rest/", "api/", "ajax", "json", "student",
                    "exam", "grade", "note", "result", "achievement",
                    "pruef", "leistung", "transcript",
                ]):
                    captured_requests.append({"url": url, "method": request.method})

            def handle_response(response):
                url = response.url
                if any(kw in url.lower() for kw in [
                    "exam", "grade", "note", "result", "achievement",
                    "pruef", "leistung", "transcript", "performance",
                    "student/my",
                ]):
                    try:
                        body = response.json()
                        print(f"\n{'='*60}")
                        print(f"INTERCEPTED: {url}")
                        print(f"STATUS: {response.status}")
                        print(f"RESPONSE (first 800 chars):")
                        print(json.dumps(body)[:800])
                    except Exception:
                        pass

            page.on("request", handle_request)
            page.on("response", handle_response)

            try:
                if not self.login(page, username, password):
                    print("Login failed")
                    return

                print("Login successful — navigating to SPA...")

                page.goto(
                    "https://campus.tum.de/tumonline/ee/ui/ca2/app/desktop/#/home?$ctx=lang=en",
                    timeout=30_000,
                )
                page.wait_for_load_state("networkidle", timeout=20_000)
                page.wait_for_timeout(2000)

                print("\nOn SPA home. Now navigating to grades/transcript section...")
                print("Try these in order in the visible browser:")
                print("1. Look for 'My Studies', 'Examinations', 'Grades', or 'Transcript'")
                print("2. Click on it and watch the terminal for intercepted API calls")
                print("3. Also try: My Studies > Examinations > Passed Examinations")
                print("\nDirect SPA URLs to try:")

                grade_routes = [
                    "#/studyplan?$ctx=lang=en",
                    "#/examinations?$ctx=lang=en",
                    "#/myexams?$ctx=lang=en",
                    "#/myresults?$ctx=lang=en",
                    "#/transcript?$ctx=lang=en",
                    "#/performance?$ctx=lang=en",
                    "#/achievements?$ctx=lang=en",
                ]

                base = "https://campus.tum.de/tumonline/ee/ui/ca2/app/desktop/"
                for route in grade_routes:
                    print(f"  {base}{route}")
                    try:
                        page.goto(f"{base}{route}", timeout=10_000)
                        page.wait_for_load_state("networkidle", timeout=8_000)
                        page.wait_for_timeout(1500)
                    except Exception:
                        pass

                print("\n\nAll API requests captured so far:")
                for r in captured_requests:
                    print(f"  [{r['method']}] {r['url']}")

                print("\n\nBrowser staying open for 60 seconds.")
                print("MANUALLY navigate to your grades/transcript page and")
                print("watch the terminal — intercepted responses will print automatically.")
                page.wait_for_timeout(60_000)

                # Fetch full achievements response programmatically for field inspection
                print("\n\n=== PROGRAMMATIC ACHIEVEMENTS FETCH ===")
                try:
                    token_data = page.evaluate("""async () => {
                        const r = await fetch('/tumonline/ee/rest/auth/token/refresh', {
                            method: 'POST',
                            headers: {Accept: 'application/json', 'Content-Type': 'application/json'},
                            body: '{}'
                        });
                        return r.ok ? await r.json() : {};
                    }""")
                    token = token_data.get("accessToken", "")
                    if token:
                        token_js_local = json.dumps(token)
                        data = page.evaluate(f"""async () => {{
                            const r = await fetch(
                                '/tumonline/ee/rest/slc.xm.ac/achievements?$orderBy=acDate=descnf&$top=3',
                                {{headers: {{Accept: 'application/json', Authorization: 'Bearer ' + {token_js_local}}}}}
                            );
                            return r.ok ? await r.json() : {{}};
                        }}""")
                        resources = data.get("resource", [])
                        print(f"Got {len(resources)} achievements")
                        for i, r in enumerate(resources[:2]):
                            dto = r.get("content", {}).get("achievementDto", {})
                            print(f"\nRecord {i+1} keys: {list(dto.keys())}")
                            print(f"Record {i+1} full: {json.dumps(dto)[:600]}")
                except Exception as e:
                    print(f"Programmatic fetch failed: {e}")

            finally:
                print("\n\nFINAL captured request list:")
                for r in captured_requests:
                    print(f"  [{r['method']}] {r['url']}")
                browser.close()

    # -------------------------------------------------------------------------
    # Course registration / deregistration (write actions)
    # -------------------------------------------------------------------------

    def _get_bearer_token(self, page) -> str:
        """Navigate SPA and return a fresh Bearer token."""
        page.goto(
            "https://campus.tum.de/tumonline/ee/ui/ca2/app/desktop/#/home?$ctx=lang=en",
            timeout=20_000,
        )
        page.wait_for_load_state("networkidle", timeout=15_000)
        page.wait_for_timeout(1000)
        token_data = page.evaluate("""async () => {
            const r = await fetch('/tumonline/ee/rest/auth/token/refresh', {
                method: 'POST',
                headers: {Accept: 'application/json', 'Content-Type': 'application/json'},
                body: '{}'
            });
            return r.ok ? await r.json() : {};
        }""")
        return token_data.get("accessToken", "")

    def search_registrable_courses(self, page, query: str) -> list[dict]:
        """Search for courses available for registration by name or keyword.

        Uses the CAMPUSonline REST API to find courses in the current semester
        that match the query and returns their IDs + titles.
        """
        token = self._get_bearer_token(page)
        if not token:
            return []

        token_js = json.dumps(token)
        import urllib.parse
        encoded_query = urllib.parse.quote(query)

        # Try the course offering search endpoint
        results = page.evaluate(f"""async () => {{
            const r = await fetch(
                '/tumonline/ee/rest/slc.tm.cp/student/courseOfferingSearch'
                + '?search={encoded_query}&$top=20&$ctx=lang=en',
                {{headers: {{Accept: 'application/json', Authorization: 'Bearer ' + {token_js}}}}}
            );
            if (!r.ok) return {{}};
            return await r.json();
        }}""")

        courses = []
        for item in results.get("resource", []):
            c = item.get("content", {}).get("courseDto", {}) or item.get("content", {})
            title_obj = c.get("courseTitle", {}) or c.get("title", {})
            title = (
                title_obj.get("value", "") if isinstance(title_obj, dict) else str(title_obj)
            )
            course_id = c.get("courseId") or c.get("id") or item.get("id")
            if title:
                courses.append({"id": course_id, "title": title, "raw": c})

        return courses

    def _navigate_to_registration_page(self, page) -> bool:
        """Navigate the SPA to the LV-Anmeldung (course registration) section."""
        spa_base = "https://campus.tum.de/tumonline/ee/ui/ca2/app/desktop/"
        candidates = [
            "#/courseRegistration?$ctx=lang=en",
            "#/lv-anmeldung?$ctx=lang=en",
            "#/enrollment?$ctx=lang=en",
            "#/myCourses?$ctx=lang=en",
        ]
        for route in candidates:
            try:
                page.goto(f"{spa_base}{route}", timeout=8_000)
                page.wait_for_load_state("networkidle", timeout=6_000)
                if "campus.tum.de" in page.url:
                    return True
            except Exception:
                continue
        return False

    def register_course(self, page, course_name: str) -> dict:
        """Attempt to register for an academic course on TUMonline.

        Strategy:
        1. Search for the course via REST API to get its ID.
        2. Try a REST POST to the registration endpoint.
        3. Fallback: navigate the SPA UI and click the Anmelden button.

        Returns a dict with keys: success (bool), message (str), course (str).
        """
        token = self._get_bearer_token(page)
        if not token:
            return {"success": False, "message": "Could not obtain auth token — is TUMonline reachable?", "course": course_name}

        token_js = json.dumps(token)

        # Step 1: find course ID via search
        courses = self.search_registrable_courses(page, course_name)
        matched = next(
            (c for c in courses if course_name.lower() in c["title"].lower()),
            courses[0] if courses else None,
        )

        if matched and matched.get("id"):
            course_id = matched["id"]
            # Step 2: POST to registration endpoint
            reg_result = page.evaluate(f"""async () => {{
                const r = await fetch(
                    '/tumonline/ee/rest/slc.tm.cp/student/courseRegistration',
                    {{
                        method: 'POST',
                        headers: {{
                            Accept: 'application/json',
                            'Content-Type': 'application/json',
                            Authorization: 'Bearer ' + {token_js}
                        }},
                        body: JSON.stringify({{courseId: {json.dumps(course_id)}}})
                    }}
                );
                return {{ok: r.ok, status: r.status, body: r.ok ? await r.json() : await r.text()}};
            }}""")

            if reg_result.get("ok"):
                return {
                    "success": True,
                    "message": f"Successfully registered for **{matched['title']}**.",
                    "course": matched["title"],
                }
            if reg_result.get("status") == 409:
                return {
                    "success": False,
                    "message": f"Already registered for **{matched['title']}** (conflict 409).",
                    "course": matched["title"],
                }

        # Step 3: Playwright UI fallback
        self._navigate_to_registration_page(page)
        page.wait_for_timeout(2000)

        # Try to search for the course in the UI
        try:
            search_box = page.locator('input[type="search"], input[placeholder*="earch"], input[placeholder*="uche"]').first
            if search_box.is_visible():
                search_box.fill(course_name)
                page.keyboard.press("Enter")
                page.wait_for_timeout(2000)
        except Exception:
            pass

        # Find and click Anmelden button
        try:
            anmelden = page.locator('button:has-text("Anmelden"), button:has-text("Register"), button:has-text("Enroll")').first
            if anmelden.is_visible():
                anmelden.click()
                page.wait_for_timeout(2000)
                # Confirm dialog if any
                confirm = page.locator('button:has-text("Confirm"), button:has-text("Bestätigen"), button:has-text("OK")').first
                if confirm.is_visible():
                    confirm.click()
                    page.wait_for_timeout(1500)
                return {
                    "success": True,
                    "message": f"Registration button clicked for **{course_name}**. Check TUMonline to confirm.",
                    "course": course_name,
                }
        except Exception as exc:
            pass

        return {
            "success": False,
            "message": (
                f"Could not register for **{course_name}** automatically. "
                "Registration periods may be closed or the course wasn't found. "
                f"Try directly on campus.tum.de"
            ),
            "course": course_name,
        }

    def deregister_course(self, page, course_name: str) -> dict:
        """Attempt to deregister from an academic course on TUMonline."""
        token = self._get_bearer_token(page)
        if not token:
            return {"success": False, "message": "Could not obtain auth token.", "course": course_name}

        token_js = json.dumps(token)

        # Step 1: find registration ID from myCourses
        data = page.evaluate(f"""async () => {{
            const r = await fetch(
                '/tumonline/ee/rest/slc.tm.cp/student/myCourses?$top=100&$ctx=lang=en',
                {{headers: {{Accept: 'application/json', Authorization: 'Bearer ' + {token_js}}}}}
            );
            return r.ok ? await r.json() : {{}};
        }}""")

        matched_reg = None
        for reg in data.get("registrations", []):
            title = reg.get("course", {}).get("courseTitle", {}).get("value", "")
            if course_name.lower() in title.lower():
                matched_reg = reg
                break

        if matched_reg:
            reg_id = matched_reg.get("registrationId") or matched_reg.get("id")
            if reg_id:
                del_result = page.evaluate(f"""async () => {{
                    const r = await fetch(
                        '/tumonline/ee/rest/slc.tm.cp/student/courseRegistration/{json.dumps(str(reg_id))}',
                        {{
                            method: 'DELETE',
                            headers: {{
                                Accept: 'application/json',
                                Authorization: 'Bearer ' + {token_js}
                            }}
                        }}
                    );
                    return {{ok: r.ok, status: r.status}};
                }}""")
                if del_result.get("ok") or del_result.get("status") in (200, 204):
                    return {
                        "success": True,
                        "message": f"Successfully deregistered from **{matched_reg.get('course', {}).get('courseTitle', {}).get('value', course_name)}**.",
                        "course": course_name,
                    }

        # Playwright UI fallback
        self._navigate_to_registration_page(page)
        page.wait_for_timeout(2000)
        try:
            abmelden = page.locator('button:has-text("Abmelden"), button:has-text("Deregister"), button:has-text("Drop")').first
            if abmelden.is_visible():
                abmelden.click()
                page.wait_for_timeout(1500)
                confirm = page.locator('button:has-text("Confirm"), button:has-text("Bestätigen"), button:has-text("OK")').first
                if confirm.is_visible():
                    confirm.click()
                return {
                    "success": True,
                    "message": f"Deregistration button clicked for **{course_name}**. Check TUMonline to confirm.",
                    "course": course_name,
                }
        except Exception:
            pass

        return {
            "success": False,
            "message": f"Could not deregister from **{course_name}** — not found in your enrolled courses or deregistration period is closed.",
            "course": course_name,
        }

    def scrape_register_course(self, username: str, password: str, course_name: str) -> dict:
        """Full workflow: login + register for a course."""
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                if not self.login(page, username, password):
                    return {"success": False, "message": "TUMonline login failed.", "course": course_name}
                return self.register_course(page, course_name)
            finally:
                browser.close()

    def scrape_deregister_course(self, username: str, password: str, course_name: str) -> dict:
        """Full workflow: login + deregister from a course."""
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                if not self.login(page, username, password):
                    return {"success": False, "message": "TUMonline login failed.", "course": course_name}
                return self.deregister_course(page, course_name)
            finally:
                browser.close()

    def scrape_with_courses(self, username: str, password: str) -> dict:
        """Full scrape: login once, then fetch deadlines AND courses/grades.

        More efficient than separate calls since login happens only once.

        Returns:
            dict with keys:
              "deadlines": list of deadline dicts
              "courses": dict from get_enrolled_courses()
        """
        from playwright.sync_api import sync_playwright

        _empty = {"deadlines": [], "courses": {"enrolled": [], "grades": {}, "all_courses": []}}

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                if not self.login(page, username, password):
                    return _empty
                deadlines = self.get_deadlines(page)
                courses = self.get_enrolled_courses(page)
                return {"deadlines": deadlines, "courses": courses}
            except Exception as exc:
                print(f"[TUMonlineConnector] scrape_with_courses error: {exc}")
                return _empty
            finally:
                browser.close()

if __name__ == "__main__":
    import os
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    username = os.getenv("TUM_USERNAME", "")
    password = os.getenv("TUM_PASSWORD", "")
    if not username or not password:
        print("Set TUM_USERNAME and TUM_PASSWORD in .env to test")
        sys.exit(1)

    if "--debug-grades" in sys.argv:
        TUMonlineConnector().debug_intercept_grade_requests(username, password)
    elif "--test-achievements" in sys.argv:
        result = TUMonlineConnector().scrape_with_courses(username, password)
        courses = result["courses"]
        print(f"\nAll completed courses ({len(courses['all_courses'])}):")
        for c in courses["all_courses"]:
            grade = courses["grades"].get(c, "no grade")
            print(f"  - {c}: {grade}")
    else:
        result = TUMonlineConnector().scrape_with_courses(username, password)
        courses = result["courses"]
        print(f"Enrolled: {courses['enrolled']}")
        print(f"Grades ({len(courses['grades'])}): {dict(list(courses['grades'].items())[:5])}")
        print(f"All courses ({len(courses['all_courses'])}): {courses['all_courses'][:10]}")
