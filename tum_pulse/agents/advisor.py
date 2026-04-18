"""AdvisorAgent: elective course recommender using Titan Embeddings + Claude."""

import json
import re
import time
from typing import Any

import requests

from tum_pulse.memory.database import SQLiteMemory
from tum_pulse.tools.bedrock_client import BedrockClient
from tum_pulse.tools.embeddings import EmbeddingsClient

TUM_API_BASE = "https://api.srv.nat.tum.de"

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


def _classify_difficulty(credits: Any, text: str) -> str:
    text_lower = text.lower()
    if any(w in text_lower for w in ["advanced", "graduate", "research", "seminar", "master"]):
        return "hard"
    if any(w in text_lower for w in ["introduction", "basic", "fundamentals", "beginner"]):
        return "easy"
    try:
        c = int(credits)
        if c >= 8:
            return "hard"
        if c <= 3:
            return "easy"
    except (TypeError, ValueError):
        pass
    return "medium"


def _extract_topics(text: str) -> list[str]:
    clean = re.sub(r"<[^>]+>", " ", text)
    words = re.findall(r"\b[a-zA-Z]{5,}\b", clean.lower())
    stop = {
        "which", "their", "these", "those", "about", "after", "before",
        "through", "using", "based", "during", "other", "where", "students",
        "course", "lecture", "exercise", "seminar", "module", "provide",
        "learn", "understanding", "knowledge", "theory", "practical",
    }
    seen: set[str] = set()
    topics: list[str] = []
    for w in words:
        if w not in stop and w not in seen:
            topics.append(w)
            seen.add(w)
        if len(topics) >= 6:
            break
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

        resp = requests.get(
            f"{TUM_API_BASE}/api/v1/mhb/module",
            params={"limit": 200, "language": "en"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        modules: list = []
        if isinstance(data, list):
            modules = data
        elif isinstance(data, dict):
            for key in ("hits", "results", "data", "modules", "items"):
                if key in data and isinstance(data[key], list):
                    modules = data[key]
                    break

        if not modules:
            print("[AdvisorAgent] No modules returned from API — using hardcoded fallback")
            return SAMPLE_ELECTIVES

        print(f"[AdvisorAgent] Got {len(modules)} modules from TUM NAT API")

        electives: list[dict] = []
        seen_names: set[str] = set()

        for module in modules:
            name = (
                module.get("module_name_en") or
                module.get("name_en") or
                module.get("title_en") or
                module.get("name") or
                module.get("title") or ""
            ).strip()

            description = (
                module.get("module_description_en") or
                module.get("description_en") or
                module.get("description") or
                module.get("content") or
                module.get("objectives") or
                name
            ).strip()

            credits = module.get("ects") or module.get("credits") or module.get("credit_points") or 0

            if not name or name in seen_names:
                continue

            module_type = str(module.get("module_type", "") or module.get("type", "")).lower()
            if any(t in module_type for t in ["pflicht", "compulsory", "mandatory", "core"]):
                continue

            full_text = f"{name} {description}"
            electives.append({
                "name": name[:80],
                "description": description[:200],
                "topics": _extract_topics(description),
                "difficulty": _classify_difficulty(credits, full_text),
                "direction": _classify_direction(full_text),
                "credits": credits,
                "module_id": module.get("id") or module.get("module_id", ""),
            })
            seen_names.add(name)

        if not electives:
            print("[AdvisorAgent] API returned modules but none passed filters — using hardcoded fallback")
            return SAMPLE_ELECTIVES

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
# Agent
# ---------------------------------------------------------------------------

class AdvisorAgent:
    """Recommends TUM electives based on student profile using semantic similarity."""

    def __init__(self, force_refresh_electives: bool = False) -> None:
        """Initialise embedding client, Bedrock client, SQLite memory, and electives."""
        self.embeddings = EmbeddingsClient()
        self.bedrock = BedrockClient()
        self.db = SQLiteMemory()
        self.electives = get_electives(self.db, force_refresh=force_refresh_electives)

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
        reasoning_text = self.bedrock.invoke(prompt, max_tokens=600)
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
    # Agent entry point
    # ------------------------------------------------------------------

    def run(self, user_input: str) -> str:
        """Extract profile from SQLite or message, return formatted recommendations.

        Args:
            user_input: Natural language request from the student.

        Returns:
            Formatted markdown string with top-5 elective recommendations.
        """
        profile: dict = {}

        saved_grades = self.db.get_profile("grades")
        saved_courses = self.db.get_profile("courses") or self.db.get_profile("enrolled")
        if saved_grades:
            profile["grades"] = saved_grades
        if saved_courses:
            profile["courses"] = saved_courses

        if not profile:
            profile = {
                "grades": {"Linear Algebra": 1.7, "Analysis": 2.3, "Algorithms and Data Structures": 2.0},
                "courses": ["Introduction to Programming", "Linear Algebra", "Analysis"],
            }

        try:
            recommendations = self.recommend(profile)
        except Exception as exc:
            return f"[AdvisorAgent] Error computing recommendations: {exc}"

        source_note = (
            f"_(Showing {len(self.electives)} real TUM electives from the module handbook)_\n\n"
            if len(self.electives) > 15
            else "_(Using sample elective catalogue)_\n\n"
        )
        lines = ["**Elective Course Recommendations for You:**\n\n" + source_note]

        for i, rec in enumerate(recommendations, 1):
            el = rec["elective"]
            lines.append(
                f"**{i}. {el['name']}** (direction: {el['direction']}, difficulty: {el['difficulty']})\n"
                f"   {el['description']}\n"
                f"   *Why this suits you:* {rec['reasoning']}\n"
            )

        self.db.save_profile("electives_count", len(self.electives))
        return "\n".join(lines)


if __name__ == "__main__":
    from tum_pulse.memory.database import SQLiteMemory
    db = SQLiteMemory()
    electives = get_electives(db, force_refresh=True)
    print(f"Fetched {len(electives)} electives")
    for e in electives[:5]:
        print(f"  [{e['direction']}] {e['name']} ({e['difficulty']})")
