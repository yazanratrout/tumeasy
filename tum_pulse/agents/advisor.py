"""AdvisorAgent: elective course recommender using Titan Embeddings + Claude."""

import json
from typing import Any

from tum_pulse.memory.database import SQLiteMemory
from tum_pulse.tools.bedrock_client import BedrockClient
from tum_pulse.tools.embeddings import EmbeddingsClient

# ---------------------------------------------------------------------------
# Hardcoded TUM elective catalogue (15 courses)
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


class AdvisorAgent:
    """Recommends TUM electives based on student profile using semantic similarity."""

    def __init__(self) -> None:
        """Initialise embedding client, Bedrock client, and SQLite memory."""
        self.embeddings = EmbeddingsClient()
        self.bedrock = BedrockClient()
        self.db = SQLiteMemory()

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
            elective: Dict from SAMPLE_ELECTIVES.

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
            # German grading: 1.0 = best, 4.0 = pass, 5.0 = fail
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
        for elective in SAMPLE_ELECTIVES:
            elective_vec = self.embed_elective(elective)
            similarity = EmbeddingsClient.cosine_similarity(profile_vec, elective_vec)
            boost = grade_boosts.get(elective["direction"], 0.0)
            final_score = similarity + boost
            scored.append({"elective": elective, "score": final_score})

        scored.sort(key=lambda x: x["score"], reverse=True)
        top5 = scored[:5]

        # Generate reasoning via Claude
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

        # Try loading saved profile from DB first
        saved_grades = self.db.get_profile("grades")
        saved_courses = self.db.get_profile("courses")
        if saved_grades:
            profile["grades"] = saved_grades
        if saved_courses:
            profile["courses"] = saved_courses

        # Minimal fallback profile if nothing is stored
        if not profile:
            profile = {
                "grades": {"Linear Algebra": 1.7, "Analysis": 2.3, "Algorithms and Data Structures": 2.0},
                "courses": ["Introduction to Programming", "Linear Algebra", "Analysis"],
            }

        try:
            recommendations = self.recommend(profile)
        except Exception as exc:
            return f"[AdvisorAgent] Error computing recommendations: {exc}"

        lines = ["**Elective Course Recommendations for You:**\n"]
        for i, rec in enumerate(recommendations, 1):
            el = rec["elective"]
            lines.append(
                f"**{i}. {el['name']}** (direction: {el['direction']}, difficulty: {el['difficulty']})\n"
                f"   {el['description']}\n"
                f"   *Why this suits you:* {rec['reasoning']}\n"
            )
        return "\n".join(lines)


if __name__ == "__main__":
    agent = AdvisorAgent()
    sample_profile = {
        "grades": {
            "Linear Algebra": 1.3,
            "Analysis": 2.0,
            "Algorithms and Data Structures": 1.7,
            "Probability Theory": 2.3,
        },
        "courses": [
            "Introduction to Programming",
            "Linear Algebra",
            "Analysis",
            "Algorithms and Data Structures",
        ],
    }
    print(agent.run("What electives should I take?"))
