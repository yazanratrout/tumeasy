"""LearningBuddyAgent: exam planner using past papers + lecture content."""

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

import requests

from tum_pulse.config import DATA_DIR, MOODLE_BASE_URL, TUM_PASSWORD, TUM_USERNAME
from tum_pulse.memory.database import SQLiteMemory
from tum_pulse.tools.bedrock_client import BedrockClient
from tum_pulse.tools.moodle_scraper import MoodleScraper


class LearningBuddyAgent:
    """Builds personalised study plans by analysing past exam papers and lectures."""

    def __init__(self) -> None:
        """Initialise dependencies: Bedrock client, Moodle scraper, SQLite memory."""
        self.bedrock = BedrockClient()
        self.scraper = MoodleScraper(
            base_url=MOODLE_BASE_URL,
            username=TUM_USERNAME,
            password=TUM_PASSWORD,
        )
        self.db = SQLiteMemory()
        Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # PDF acquisition
    # ------------------------------------------------------------------

    def download_moodle_pdfs(self, course_name: str) -> list[str]:
        """Download PDFs for *course_name* from Moodle.

        Args:
            course_name: Human-readable course name used to match Moodle files.

        Returns:
            List of local file paths to downloaded PDFs.

        TODO: Real Moodle scraping requires:
              1. Call self.scraper.login() with valid TUM SSO credentials
              2. Look up the numeric Moodle course ID from a course catalogue call
              3. Call self.scraper.get_course_files(course_id) to get file list
              4. Filter for PDFs and call self.scraper.download_pdf() for each
              5. Return local paths
        """
        files = self.scraper.get_sample_data()
        course_lower = course_name.lower().replace(" ", "_")
        local_paths: list[str] = []

        for file_meta in files:
            filename = file_meta["name"]
            save_path = str(Path(DATA_DIR) / filename)

            # For demo: create a placeholder text file since real Moodle auth is absent
            if not Path(save_path).exists():
                with open(save_path, "w") as fh:
                    fh.write(
                        f"[SAMPLE CONTENT for {filename}]\n"
                        "This is placeholder text generated for demo purposes.\n"
                        f"Course: {course_name}\n"
                        "Topics: integration, differentiation, series, limits, continuity.\n"
                        "Past exam focus: Taylor series, Fourier series, multivariable calculus.\n"
                        "Typical point distribution: 30% integration, 25% series, 20% differential equations, 25% theory.\n"
                    )
            local_paths.append(save_path)

        return local_paths

    # ------------------------------------------------------------------
    # Text extraction
    # ------------------------------------------------------------------

    def extract_text_from_pdfs(self, pdf_paths: list[str]) -> dict[str, str]:
        """Extract text from PDF files using PyMuPDF.

        Args:
            pdf_paths: List of local file paths to PDFs (or placeholder .txt files).

        Returns:
            Dict mapping filename → extracted text.
        """
        texts: dict[str, str] = {}

        for path in pdf_paths:
            filename = Path(path).name
            try:
                import fitz  # PyMuPDF

                doc = fitz.open(path)
                text = "\n".join(page.get_text() for page in doc)
                doc.close()
                texts[filename] = text
            except ImportError:
                # PyMuPDF not available — fall back to reading plain text
                try:
                    with open(path, "r", errors="ignore") as fh:
                        texts[filename] = fh.read()
                except Exception as exc:
                    texts[filename] = f"[Could not read file: {exc}]"
            except Exception as exc:
                texts[filename] = f"[Extraction error: {exc}]"

        return texts

    # ------------------------------------------------------------------
    # Paper analysis
    # ------------------------------------------------------------------

    def analyse_past_papers(
        self, past_paper_text: str, lecture_texts: dict[str, str]
    ) -> dict:
        """Use Claude to identify and prioritise exam topics.

        Args:
            past_paper_text: Combined text from past exam papers.
            lecture_texts: Dict of lecture filename → text.

        Returns:
            Structured dict:
            {
                "topics": [
                    {
                        "name": str,
                        "frequency": int,
                        "points_weight": float,
                        "in_lectures": bool,
                        "priority_score": float
                    }
                ]
            }
        """
        lecture_summary = "\n".join(
            f"--- {name} ---\n{text[:500]}" for name, text in lecture_texts.items()
        )

        prompt = f"""You are an expert exam analyst. Analyse the following past exam papers and lecture notes.

PAST EXAM PAPERS:
{past_paper_text[:3000]}

LECTURE CONTENT (excerpts):
{lecture_summary[:2000]}

Return a JSON object with the following structure:
{{
  "topics": [
    {{
      "name": "topic name",
      "frequency": <number of times topic appeared in exams>,
      "points_weight": <estimated percentage of total exam points>,
      "in_lectures": <true if topic is covered in lecture notes>,
      "priority_score": <0.0 to 1.0, combining frequency and points_weight>
    }}
  ]
}}

Identify ALL distinct topics. Order by priority_score descending. Return ONLY valid JSON, no explanation."""

        raw = self.bedrock.invoke(prompt, max_tokens=1500)

        try:
            # Extract JSON block if Claude wraps it in markdown
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            return json.loads(raw.strip())
        except (json.JSONDecodeError, IndexError):
            # Fallback structured response
            return {
                "topics": [
                    {"name": "Integration techniques", "frequency": 5, "points_weight": 30.0, "in_lectures": True, "priority_score": 0.9},
                    {"name": "Taylor and Fourier series", "frequency": 4, "points_weight": 25.0, "in_lectures": True, "priority_score": 0.85},
                    {"name": "Differential equations", "frequency": 3, "points_weight": 20.0, "in_lectures": True, "priority_score": 0.75},
                    {"name": "Multivariable calculus", "frequency": 3, "points_weight": 15.0, "in_lectures": True, "priority_score": 0.65},
                    {"name": "Limits and continuity", "frequency": 2, "points_weight": 10.0, "in_lectures": True, "priority_score": 0.5},
                ]
            }

    # ------------------------------------------------------------------
    # Study plan generation
    # ------------------------------------------------------------------

    def generate_study_plan(self, analysis: dict, course_name: str) -> str:
        """Generate a week-by-week study plan from topic analysis.

        Args:
            analysis: Output of analyse_past_papers().
            course_name: Name of the course for contextualisation.

        Returns:
            Formatted markdown study plan.
        """
        topics_json = json.dumps(analysis, indent=2)

        prompt = f"""You are an expert academic tutor helping a TUM student prepare for their {course_name} exam.

Based on this topic analysis from past papers:
{topics_json}

Create a concise, realistic week-by-week study plan for 4 weeks before the exam.
- Prioritise topics by priority_score (highest first)
- Each week should have 3-4 specific study goals
- Include one practice/revision day per week
- Keep each week's description to 3-4 bullet points
- End with a "Final Week" sprint section

Format as clean markdown with ## Week headers."""

        return self.bedrock.invoke(prompt, max_tokens=1200)

    # ------------------------------------------------------------------
    # Agent entry point
    # ------------------------------------------------------------------

    def run(self, user_input: str) -> str:
        """Orchestrate the full exam planning pipeline.

        Args:
            user_input: Natural language request, e.g. "Help me prepare for Analysis 2".

        Returns:
            Formatted markdown study plan.
        """
        # Extract course name from input (simple heuristic)
        course_name = "Analysis 2"  # default
        keywords = ["for", "pass", "prepare", "exam", "study"]
        words = user_input.split()
        for i, word in enumerate(words):
            if word.lower() in keywords and i + 1 < len(words):
                candidate = " ".join(words[i + 1 : i + 3]).strip(".,?!")
                if len(candidate) > 3:
                    course_name = candidate
                    break

        try:
            pdf_paths = self.download_moodle_pdfs(course_name)
            texts = self.extract_text_from_pdfs(pdf_paths)

            past_papers = {k: v for k, v in texts.items() if "exam" in k.lower() or "past" in k.lower()}
            lectures = {k: v for k, v in texts.items() if k not in past_papers}

            past_paper_text = "\n\n".join(past_papers.values()) if past_papers else "\n\n".join(list(texts.values())[:1])
            lecture_texts = lectures if lectures else texts

            analysis = self.analyse_past_papers(past_paper_text, lecture_texts)
            study_plan = self.generate_study_plan(analysis, course_name)

            header = f"# Study Plan: {course_name}\n\n"
            topic_summary = "## Top Priority Topics\n" + "\n".join(
                f"- **{t['name']}** — priority {t['priority_score']:.2f} ({t['points_weight']:.0f}% of exam)"
                for t in analysis.get("topics", [])[:5]
            ) + "\n\n---\n\n"

            return header + topic_summary + study_plan

        except Exception as exc:
            return f"[LearningBuddyAgent] Error generating study plan: {exc}"


if __name__ == "__main__":
    agent = LearningBuddyAgent()
    print(agent.run("Help me pass Analysis 2"))
