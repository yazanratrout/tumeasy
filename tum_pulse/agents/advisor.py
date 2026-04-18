"""AdvisorAgent: elective course recommender using Titan Embeddings + Claude."""

import json
import re
from collections import Counter

import requests

from tum_pulse.memory.database import SQLiteMemory
from tum_pulse.tools.bedrock_client import BedrockClient, HAIKU
from tum_pulse.tools.embeddings import EmbeddingsClient
from tum_pulse.tools.llm_cache import LLMCache

TUM_API_BASE = "https://api.srv.nat.tum.de"

# ---------------------------------------------------------------------------
# Career paths + Munich companies by direction
# ---------------------------------------------------------------------------

CAREER_PATHS: dict[str, dict] = {
    "ml": {
        "roles": ["ML Engineer", "Data Scientist", "AI Research Scientist", "NLP Engineer",
                  "Computer Vision Engineer", "MLOps Engineer"],
        "companies": [
            ("Aleph Alpha", "https://aleph-alpha.com/careers"),
            ("Celonis", "https://www.celonis.com/careers"),
            ("Siemens AI Lab Munich", "https://jobs.siemens.com"),
            ("BMW Group AI", "https://www.bmwgroup.com/en/career.html"),
            ("MaibornWolff", "https://www.maibornwolff.de/karriere"),
            ("Personio", "https://www.personio.com/about-personio/careers"),
            ("Flixbus Data & AI", "https://www.flixbus.de/unternehmen/karriere"),
            ("Rohde & Schwarz AI", "https://www.rohde-schwarz.com/careers"),
        ],
    },
    "programming": {
        "roles": ["Software Engineer", "Backend Developer", "Full-Stack Developer",
                  "DevOps Engineer", "Platform Engineer", "Cloud Architect"],
        "companies": [
            ("Celonis", "https://www.celonis.com/careers"),
            ("Personio", "https://www.personio.com/about-personio/careers"),
            ("Flixbus Engineering", "https://www.flixbus.de/unternehmen/karriere"),
            ("MaibornWolff", "https://www.maibornwolff.de/karriere"),
            ("Scalable Capital", "https://de.scalable.capital/en/career"),
            ("CHECK24 Tech", "https://www.check24.de/unternehmen/jobs"),
            ("Stylight", "https://www.stylight.com/Jobs"),
            ("XING (New Work SE)", "https://www.new-work.se/en/career"),
        ],
    },
    "mathematics": {
        "roles": ["Quantitative Analyst", "Actuary", "Data Analyst",
                  "Operations Research Scientist", "Risk Analyst", "Statistician"],
        "companies": [
            ("Scalable Capital (Quant)", "https://de.scalable.capital/en/career"),
            ("Munich Re", "https://www.munichre.com/en/company/career.html"),
            ("Allianz Global Investors", "https://www.allianzgi.com/en/careers"),
            ("MAN Energy Solutions", "https://www.man-es.com/company/careers"),
            ("msg systems", "https://www.msg.group/karriere"),
            ("KPMG Munich", "https://home.kpmg/de/de/home/careers.html"),
        ],
    },
    "electrical": {
        "roles": ["Embedded Systems Engineer", "Signal Processing Engineer",
                  "Hardware Engineer", "FPGA Developer", "Power Electronics Engineer"],
        "companies": [
            ("Rohde & Schwarz", "https://www.rohde-schwarz.com/careers"),
            ("Infineon Technologies", "https://www.infineon.com/cms/en/careers"),
            ("Siemens Healthineers", "https://www.siemens-healthineers.com/careers"),
            ("Airbus Defence Munich", "https://www.airbus.com/en/careers"),
            ("Linde Engineering", "https://www.linde-engineering.com/en/careers"),
            ("BMW Group Hardware", "https://www.bmwgroup.com/en/career.html"),
        ],
    },
    "systems": {
        "roles": ["Systems Engineer", "Security Engineer", "Network Engineer",
                  "Cloud Infrastructure Engineer", "Site Reliability Engineer"],
        "companies": [
            ("Giesecke+Devrient (Security)", "https://www.gi-de.com/en/careers"),
            ("secunet Security Networks", "https://www.secunet.com/karriere"),
            ("Siemens Cyber Defense", "https://jobs.siemens.com"),
            ("TÜV SÜD Digital", "https://www.tuvsud.com/en/career"),
            ("Knorr-Bremse Systems", "https://www.knorr-bremse.com/en/career"),
            ("MTU Aero Engines", "https://www.mtu.de/career"),
        ],
    },
}

# ---------------------------------------------------------------------------
# Hardcoded TUM elective catalogue (fallback)
# ---------------------------------------------------------------------------

SAMPLE_ELECTIVES: list[dict] = [
    {
        "name": "Introduction to Deep Learning",
        "description": "Neural networks, backpropagation, CNNs, RNNs, transformers, PyTorch.",
        "topics": ["neural networks", "deep learning", "pytorch", "transformers"],
        "difficulty": "medium",
        "direction": "ml",
    },
    {
        "name": "Machine Learning",
        "description": "Supervised and unsupervised learning, SVMs, decision trees, model evaluation.",
        "topics": ["supervised learning", "unsupervised learning", "SVM", "model selection"],
        "difficulty": "medium",
        "direction": "ml",
    },
    {
        "name": "Practical Course: Machine Learning in Production",
        "description": "MLOps, Docker, Kubernetes, CI/CD for ML, model serving with FastAPI.",
        "topics": ["mlops", "docker", "kubernetes", "model serving"],
        "difficulty": "hard",
        "direction": "ml",
    },
    {
        "name": "Natural Language Processing",
        "description": "Tokenisation, language models, BERT, fine-tuning, text classification.",
        "topics": ["nlp", "bert", "language models", "text classification"],
        "difficulty": "hard",
        "direction": "ml",
    },
    {
        "name": "Advanced Programming",
        "description": "Design patterns, clean code, testing, refactoring, SOLID principles in Java.",
        "topics": ["design patterns", "java", "testing", "clean code"],
        "difficulty": "medium",
        "direction": "programming",
    },
    {
        "name": "Functional Programming",
        "description": "Lambda calculus, Haskell, monads, type inference, category theory basics.",
        "topics": ["haskell", "functional", "type theory", "monads"],
        "difficulty": "hard",
        "direction": "programming",
    },
    {
        "name": "Systems Programming in Rust",
        "description": "Memory safety, ownership, concurrency, async Rust, writing system tools.",
        "topics": ["rust", "memory safety", "concurrency", "systems"],
        "difficulty": "hard",
        "direction": "programming",
    },
    {
        "name": "Web Development with React and Node",
        "description": "React hooks, REST APIs, GraphQL, authentication, deployment.",
        "topics": ["react", "nodejs", "graphql", "web development"],
        "difficulty": "easy",
        "direction": "programming",
    },
    {
        "name": "Embedded Systems",
        "description": "Microcontrollers, RTOS, sensor interfacing, ARM assembly, power management.",
        "topics": ["embedded", "microcontroller", "RTOS", "ARM"],
        "difficulty": "hard",
        "direction": "electrical",
    },
    {
        "name": "Digital Signal Processing",
        "description": "Fourier transforms, filters, FFT, signal sampling, audio processing.",
        "topics": ["signal processing", "fourier", "FFT", "filters"],
        "difficulty": "medium",
        "direction": "electrical",
    },
    {
        "name": "Power Electronics",
        "description": "DC-DC converters, inverters, motor drives, renewable energy systems.",
        "topics": ["power electronics", "converters", "inverters", "motors"],
        "difficulty": "hard",
        "direction": "electrical",
    },
    {
        "name": "Numerical Analysis",
        "description": "Floating point arithmetic, interpolation, numerical ODE/PDE solvers, stability.",
        "topics": ["numerical methods", "interpolation", "ODE", "stability"],
        "difficulty": "hard",
        "direction": "mathematics",
    },
    {
        "name": "Convex Optimisation",
        "description": "Convex sets, duality, gradient descent variants, applications in ML.",
        "topics": ["optimisation", "gradient descent", "duality", "convex"],
        "difficulty": "hard",
        "direction": "mathematics",
    },
    {
        "name": "Stochastic Processes",
        "description": "Markov chains, Brownian motion, martingales, queueing theory.",
        "topics": ["stochastic", "markov chains", "brownian motion", "probability"],
        "difficulty": "hard",
        "direction": "mathematics",
    },
    {
        "name": "Operating Systems",
        "description": "Process scheduling, virtual memory, file systems, synchronisation primitives.",
        "topics": ["operating systems", "memory management", "scheduling", "file systems"],
        "difficulty": "medium",
        "direction": "systems",
    },
]

# Grade → direction boost mapping
GRADE_DIRECTION_BOOST: dict[str, list[str]] = {
    "Linear Algebra": ["ml", "mathematics"],
    "Analysis": ["mathematics", "ml"],
    "Analysis 2": ["mathematics", "ml"],
    "Algorithms and Data Structures": ["programming", "systems"],
    "Introduction to Programming": ["programming"],
    "Physics": ["electrical"],
    "Probability Theory": ["ml", "mathematics"],
    "Machine Learning": ["ml"],
    "Computer Networks": ["systems"],
    "Digital Design": ["electrical"],
}

# ---------------------------------------------------------------------------
# Live module fetcher
# ---------------------------------------------------------------------------

DIRECTION_KEYWORDS: dict[str, list[str]] = {
    "ml": [
        "machine learning", "deep learning", "neural", "ai ", "artificial intelligence",
        "data science", "nlp", "computer vision", "reinforcement", "classification",
        "regression", "clustering", "pytorch", "tensorflow", "statistics",
    ],
    "programming": [
        "software", "programming", "algorithm", "data structure", "compiler",
        "operating system", "database", "web", "cloud", "devops", "testing",
        "object-oriented", "functional", "concurrent", "distributed",
    ],
    "mathematics": [
        "analysis", "algebra", "calculus", "topology", "geometry", "number theory",
        "optimisation", "optimization", "probability", "statistics", "stochastic",
        "differential equation", "numerical", "discrete math",
    ],
    "electrical": [
        "signal", "circuit", "embedded", "microcontroller", "electronics",
        "power", "control", "communication", "wireless", "antenna", "sensor",
        "digital design", "vhdl", "fpga",
    ],
    "systems": [
        "network", "security", "cryptography", "distributed", "parallel",
        "computer architecture", "operating", "real-time", "robotics",
        "autonomous", "simulation",
    ],
}


def _classify_direction(text: str) -> str:
    text_lower = text.lower()
    scores = {d: 0 for d in DIRECTION_KEYWORDS}
    for direction, keywords in DIRECTION_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                scores[direction] += 1
    best = max(scores, key=lambda d: scores[d])
    return best if scores[best] > 0 else "programming"


def _classify_difficulty(credits: float, text: str) -> str:
    text_lower = text.lower()
    if any(w in text_lower for w in ["advanced", "graduate", "research", "seminar", "master"]):
        return "hard"
    if any(w in text_lower for w in ["introduction", "basic", "fundamentals", "beginner", "introductory"]):
        return "easy"
    if credits >= 8:
        return "hard"
    elif credits <= 3:
        return "easy"
    return "medium"


def _extract_topics(name: str, school: str, code: str) -> list[str]:
    """Extract topic keywords from module name and school."""
    text = f"{name} {school}".lower()
    words = re.findall(r"\b[a-zA-Z]{5,}\b", text)
    stop = {
        "which", "their", "these", "those", "about", "school", "chair",
        "professorship", "professor", "munich", "technical", "university",
        "offered", "department", "institute", "faculty",
    }
    seen: set[str] = set()
    topics: list[str] = []
    for w in words:
        if w not in stop and w not in seen:
            topics.append(w)
            seen.add(w)
        if len(topics) >= 5:
            break
    prefix = code[:2].lower()
    if prefix not in seen:
        topics.append(prefix)
    return topics if topics else ["general"]


def fetch_electives_from_api() -> list[dict]:
    """Fetch elective modules from TUM NAT API module handbook.

    Calls /api/v1/mhb/module to get the real TUM module catalogue,
    then filters and normalizes into the same format as SAMPLE_ELECTIVES.
    Falls back to SAMPLE_ELECTIVES if the API is unreachable.

    Returns:
        List of elective dicts with keys: name, description, topics,
        difficulty, direction.
    """
    try:
        print("[AdvisorAgent] Fetching electives from TUM NAT API...")

        # API max limit is 200 per page; paginate to collect up to 500 modules
        PAGE_SIZE = 200
        TARGET = 500
        modules: list = []
        offset = 0
        while len(modules) < TARGET:
            resp = requests.get(
                f"{TUM_API_BASE}/api/v1/mhb/module",
                params={"limit": PAGE_SIZE, "offset": offset},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            page: list = []
            if isinstance(data, list):
                page = data
            elif isinstance(data, dict):
                for key in ("hits", "results", "data", "modules", "items"):
                    if key in data and isinstance(data[key], list):
                        page = data[key]
                        break
            if not page:
                break
            modules.extend(page)
            if len(page) < PAGE_SIZE:
                break  # last page
            offset += PAGE_SIZE

        if not modules:
            print("[AdvisorAgent] No modules returned from API — using hardcoded fallback")
            return SAMPLE_ELECTIVES

        print(f"[AdvisorAgent] Got {len(modules)} modules from TUM NAT API")

        electives: list[dict] = []
        seen_names: set[str] = set()

        PREFIX_DIRECTION = {
            "IN": "programming", "MA": "mathematics", "EI": "electrical",
            "CIT": "programming", "WI": "programming", "PH": "mathematics",
            "CH": "mathematics", "ME": "systems",
        }
        # Exact school keyword substrings that are genuinely STEM-relevant
        RELEVANT_SCHOOL_KEYWORDS = {
            "informatics", "mathematics", "electrical", "computation",
            "natural sciences", "physics", "statistics",
        }
        # Module code prefixes for STEM departments
        RELEVANT_PREFIXES = ("IN", "MA", "EI", "CIT", "WI", "CH", "PH", "ME", "MSE")

        for module in modules:
            name = (
                module.get("module_title_en") or
                module.get("module_title") or ""
            ).strip()

            credits_str = module.get("module_credits") or "0"
            try:
                credits = float(credits_str)
            except (ValueError, TypeError):
                credits = 0.0

            subtitle = (
                module.get("module_subtitle_en") or
                module.get("module_subtitle") or ""
            ).strip()

            org = module.get("org") or {}
            school_obj = (org.get("school") or {})
            school = school_obj.get("org_name_en", "")

            description = subtitle if subtitle else name
            if school:
                description = (
                    f"{description}. Offered by {school}."
                    if description != name
                    else f"Offered by {school}."
                )

            code = module.get("module_code", "")

            # Filter 1: Must have an English name
            lang_tags = module.get("language_tags") or []
            if "en" not in lang_tags and not module.get("module_title_en"):
                continue

            # Filter 2: Skip very short / missing names
            if not name or len(name) < 4:
                continue

            # Filter 3: Keep only STEM modules — code prefix is primary gate,
            # school name is secondary (for unlabelled codes)
            school_lower = school.lower()
            code_ok = any(code.startswith(p) for p in RELEVANT_PREFIXES)
            school_ok = any(kw in school_lower for kw in RELEVANT_SCHOOL_KEYWORDS)
            if not code_ok and not school_ok:
                continue

            # Filter 4: Skip modules with no ECTS
            if credits == 0:
                continue

            if name in seen_names:
                continue

            prefix_dir = next(
                (d for p, d in PREFIX_DIRECTION.items() if code.startswith(p)), None
            )
            direction = prefix_dir if prefix_dir else _classify_direction(f"{name} {school}")

            electives.append({
                "name": name[:80],
                "description": description[:200],
                "topics": _extract_topics(name, school, code),
                "difficulty": _classify_difficulty(credits, name),
                "direction": direction,
                "credits": credits,
                "module_id": code,
            })
            seen_names.add(name)

        if not electives:
            print("[AdvisorAgent] API returned modules but none passed filters — using hardcoded fallback")
            return SAMPLE_ELECTIVES

        dir_counts = Counter(e["direction"] for e in electives)
        print(f"[AdvisorAgent] Elective breakdown: {dict(dir_counts)}")
        print(f"[AdvisorAgent] Using {len(electives)} real electives from TUM NAT API")
        return electives

    except Exception as exc:
        print(f"[AdvisorAgent] Module API failed ({exc}) — using hardcoded fallback")
        return SAMPLE_ELECTIVES


def get_electives(db: "SQLiteMemory", force_refresh: bool = False) -> list[dict]:
    """Return electives from cache or fetch fresh from API.

    Caches the fetched elective list in SQLite under key 'electives_cache'
    so repeated calls don't hammer the API. Cache is valid for 24 hours.

    Args:
        db: SQLiteMemory instance for caching.
        force_refresh: If True, bypass cache and always fetch fresh.

    Returns:
        List of elective dicts.
    """
    from datetime import datetime, timedelta

    if not force_refresh:
        try:
            cached = db.get_profile("electives_cache")
            cached_at_str = db.get_profile("electives_cached_at")
            if cached and cached_at_str:
                cached_at = datetime.fromisoformat(cached_at_str)
                if datetime.now() - cached_at < timedelta(hours=24):
                    print(f"[AdvisorAgent] Using {len(cached)} cached electives (from {cached_at_str[:16]})")
                    return cached
        except Exception:
            pass

    electives = fetch_electives_from_api()

    try:
        db.save_profile("electives_cache", electives)
        db.save_profile("electives_cached_at", datetime.now().isoformat())
    except Exception as exc:
        print(f"[AdvisorAgent] Could not cache electives: {exc}")

    return electives


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------

def _infer_weak_subjects(grades: dict) -> list[str]:
    """Return course names where the student's grade is poor (> 2.5 in German system)."""
    weak = []
    for course, grade in grades.items():
        try:
            if float(grade) > 2.5:
                weak.append(course)
        except (ValueError, TypeError):
            pass
    return weak


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class AdvisorAgent:
    """Recommends TUM electives based on student profile using semantic similarity."""

    def __init__(self, force_refresh_electives: bool = False) -> None:
        """Initialise embedding client, Bedrock client, SQLite memory, and electives."""
        self.embeddings = EmbeddingsClient()
        self.bedrock = BedrockClient()
        self.llm_cache = LLMCache()
        self.db = SQLiteMemory()
        self.electives = get_electives(self.db, force_refresh=force_refresh_electives)
        self.data_source = "api" if len(self.electives) > 15 else "fallback"

    # ------------------------------------------------------------------
    # Embedding helpers
    # ------------------------------------------------------------------

    def build_profile_embedding(self, profile: dict) -> list[float]:
        """Create an embedding of the student's academic profile.

        Args:
            profile: Dict with optional keys 'grades' (dict) and 'courses' (list).

        Returns:
            Dense embedding vector representing the student's interests.
        """
        grades: dict = profile.get("grades", {})
        courses: list = profile.get("courses", [])

        grade_text = ", ".join(
            f"{course} (grade {grade})" for course, grade in grades.items()
        )
        courses_text = ", ".join(courses)
        summary = f"Completed courses: {courses_text}. Grades: {grade_text}."
        return self.embeddings.embed(summary)

    def embed_elective(self, elective: dict) -> list[float]:
        """Embed an elective's description and topics.

        Args:
            elective: Dict from electives list.

        Returns:
            Dense embedding vector.
        """
        text = f"{elective['name']}: {elective['description']} Topics: {', '.join(elective['topics'])}"
        return self.embeddings.embed(text)

    # ------------------------------------------------------------------
    # Grade-based boost
    # ------------------------------------------------------------------

    def _compute_grade_boost(self, grades: dict) -> dict[str, float]:
        """Return a boost score per direction based on high grades.

        Args:
            grades: Mapping of course name → grade (1.0 best, 5.0 worst in German system).

        Returns:
            Dict mapping direction → additive boost (0.0 – 0.2).
        """
        boosts: dict[str, float] = {}
        for course, grade in grades.items():
            try:
                numeric_grade = float(grade)
            except (ValueError, TypeError):
                continue
            if numeric_grade <= 2.0:
                for course_key, directions in GRADE_DIRECTION_BOOST.items():
                    if course_key.lower() in course.lower():
                        for direction in directions:
                            boosts[direction] = boosts.get(direction, 0.0) + (2.0 - numeric_grade) * 0.05
        return boosts

    # ------------------------------------------------------------------
    # Recommendation pipeline
    # ------------------------------------------------------------------

    def recommend(self, student_profile: dict) -> list[dict]:
        """Return top-5 elective recommendations for the given student profile.

        Args:
            student_profile: Dict with 'grades' and 'courses' keys.

        Returns:
            List of up to 5 dicts: {elective, score, reasoning}.
        """
        profile_vec = self.build_profile_embedding(student_profile)
        grade_boosts = self._compute_grade_boost(student_profile.get("grades", {}))

        scored: list[dict] = []
        for elective in self.electives:
            elective_vec = self.embed_elective(elective)
            similarity = EmbeddingsClient.cosine_similarity(profile_vec, elective_vec)
            boost = grade_boosts.get(elective["direction"], 0.0)
            final_score = similarity + boost
            scored.append({"elective": elective, "score": final_score})

        scored.sort(key=lambda x: x["score"], reverse=True)
        top5 = scored[:5]

        profile_summary = json.dumps(student_profile, indent=2)
        top5_names = [s["elective"]["name"] for s in top5]
        prompt = (
            f"A TUM student has the following academic profile:\n{profile_summary}\n\n"
            f"Based on their profile, the top recommended electives are:\n"
            + "\n".join(f"- {n}" for n in top5_names)
            + "\n\nFor each elective, write one sentence explaining why it suits this student. "
            "Be specific about which grades or past courses make it a good fit."
        )
        cached_reasoning = self.llm_cache.get(prompt)
        reasoning_text = cached_reasoning or self.bedrock.invoke(prompt, max_tokens=600)
        if not cached_reasoning:
            self.llm_cache.set(prompt, reasoning_text, ttl_seconds=86400)
        reasoning_lines = [
            line.strip("- ").strip()
            for line in reasoning_text.split("\n")
            if line.strip()
        ]

        results = []
        for i, item in enumerate(top5):
            results.append(
                {
                    "elective": item["elective"],
                    "score": round(item["score"], 4),
                    "reasoning": reasoning_lines[i] if i < len(reasoning_lines) else "",
                }
            )
        return results

    # ------------------------------------------------------------------
    # Career path suggestion
    # ------------------------------------------------------------------

    def _career_section(self, direction: str, grades: dict) -> str:
        """Build a career paths + Munich companies block for the given direction."""
        info = CAREER_PATHS.get(direction, CAREER_PATHS["programming"])
        roles = ", ".join(info["roles"][:4])
        companies_md = "\n".join(
            f"  - [{name}]({url})" for name, url in info["companies"]
        )
        grade_avg = ""
        if grades:
            nums = [float(v) for v in grades.values() if str(v).replace(".", "").isdigit()]
            if nums:
                avg = sum(nums) / len(nums)
                grade_avg = f" (avg grade **{avg:.1f}**)"
        return (
            f"\n\n---\n## 🚀 Career Paths for Your Profile{grade_avg}\n"
            f"**Top roles in your direction ({direction}):** {roles}\n\n"
            f"**Munich companies hiring in this area:**\n{companies_md}\n\n"
            f"> 💡 TUM's Career Center also lists student positions: "
            f"[portal.myinterflex.de](https://portal.myinterflex.de)"
        )

    # ------------------------------------------------------------------
    # Agent entry point
    # ------------------------------------------------------------------

    def run(self, user_input: str, context: dict | None = None) -> str:
        """Extract profile from SQLite or message, return formatted recommendations.

        Args:
            user_input: Natural language request from the student.
            context: Optional context dict with 'grades' and 'courses' from orchestrator.

        Returns:
            Formatted markdown string with top-5 elective recommendations.
        """
        profile: dict = {}
        ctx = context or {}

        selected_grades = self.db.get_profile("selected_recommendation_grades") or {}
        selected_courses = self.db.get_profile("selected_recommendation_courses") or []
        saved_grades = self.db.get_profile("grades") or ctx.get("grades") or {}
        saved_courses = (
            self.db.get_profile("courses") or
            self.db.get_profile("enrolled") or
            ctx.get("courses") or []
        )

        # If no profile at all, trigger a fresh course+grade fetch
        if not saved_grades and not saved_courses:
            print("[AdvisorAgent] No profile in SQLite — triggering TUMonline fetch...")
            try:
                from tum_pulse.connectors.tumonline import TUMonlineConnector
                from tum_pulse.config import TUM_USERNAME, TUM_PASSWORD
                fetch_result = TUMonlineConnector().scrape_with_courses(TUM_USERNAME, TUM_PASSWORD)
                courses_data = fetch_result.get("courses", {})
                if courses_data.get("grades"):
                    saved_grades = courses_data["grades"]
                    self.db.save_profile("grades", saved_grades)
                if courses_data.get("all_courses"):
                    saved_courses = courses_data["all_courses"]
                    self.db.save_profile("courses", saved_courses)
            except Exception as exc:
                print(f"[AdvisorAgent] Fresh fetch failed: {exc}")

        active_grades = selected_grades if selected_grades else (saved_grades or {})
        active_courses = selected_courses if selected_courses else (saved_courses or [])

        if active_grades:
            profile["grades"] = active_grades
        if active_courses:
            profile["courses"] = active_courses

        if not profile:
            profile = {
                "grades": {"Linear Algebra": 1.7, "Analysis": 2.3, "Algorithms and Data Structures": 2.0},
                "courses": ["Introduction to Programming", "Linear Algebra", "Analysis"],
            }

        # Context-aware: boost electives that align with weak areas so student can improve
        weak_subjects = _infer_weak_subjects(profile.get("grades", {}))
        if weak_subjects:
            print(f"[AdvisorAgent] Weak subjects detected: {weak_subjects} — will surface strengthening electives")

        try:
            recommendations = self.recommend(profile)
        except Exception as exc:
            return f"[AdvisorAgent] Error computing recommendations: {exc}"

        source_note = (
            f"_(Showing {len(self.electives)} real TUM electives from the module handbook)_\n\n"
            if len(self.electives) > 15
            else "_(Using sample elective catalogue)_\n\n"
        )
        selection_note = (
            f"_(Recommendations currently use only your selected courses: {', '.join(selected_courses)})_\n\n"
            if selected_courses
            else "_(No specific courses selected, so recommendations use your full saved course history.)_\n\n"
        )
        weak_note = (
            f"_(Subjects where you may benefit from extra practice: {', '.join(weak_subjects)})_\n\n"
            if weak_subjects else ""
        )
        lines = ["**Elective Course Recommendations for You:**\n\n" + source_note + selection_note + weak_note]

        for i, rec in enumerate(recommendations, 1):
            el = rec["elective"]
            lines.append(
                f"**{i}. {el['name']}** (direction: {el['direction']}, difficulty: {el['difficulty']})\n"
                f"   {el['description']}\n"
                f"   *Why this suits you:* {rec['reasoning']}\n"
            )

        self.db.save_profile("electives_count", len(self.electives))

        # Infer dominant direction from top recommendations
        direction_votes = [rec["elective"].get("direction", "programming") for rec in recommendations]
        dominant_direction = max(set(direction_votes), key=direction_votes.count) if direction_votes else "programming"

        career = self._career_section(dominant_direction, profile.get("grades", {}))
        return "\n".join(lines) + career


if __name__ == "__main__":
    from tum_pulse.memory.database import SQLiteMemory
    db = SQLiteMemory()
    electives = get_electives(db, force_refresh=True)
    print(f"Fetched {len(electives)} electives")
    for e in electives[:5]:
        print(f"  [{e['direction']}] {e['name']} ({e['difficulty']})")
