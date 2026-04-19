"""CV Maker — generates a themed, professional PDF CV from structured user data."""

from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

PAGE_W, _ = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

# ---------------------------------------------------------------------------
# Per-direction color themes
# ---------------------------------------------------------------------------

DIRECTION_THEMES: dict[str, dict] = {
    "ml": {
        "label": "🤖 AI / Machine Learning",
        "accent": HexColor("#0065BD"),
        "accent_hex": "#0065BD",
        "header_bg": HexColor("#003359"),
        "section_order": ["profile", "experience", "skills", "projects", "education"],
    },
    "programming": {
        "label": "💻 Software Engineering",
        "accent": HexColor("#1a7f37"),
        "accent_hex": "#1a7f37",
        "header_bg": HexColor("#0d4a21"),
        "section_order": ["profile", "experience", "projects", "skills", "education"],
    },
    "mathematics": {
        "label": "📐 Mathematics / Quant",
        "accent": HexColor("#7c3aed"),
        "accent_hex": "#7c3aed",
        "header_bg": HexColor("#4c1d95"),
        "section_order": ["profile", "education", "experience", "skills", "projects"],
    },
    "electrical": {
        "label": "⚡ Electrical / Embedded",
        "accent": HexColor("#E37222"),
        "accent_hex": "#E37222",
        "header_bg": HexColor("#92400e"),
        "section_order": ["profile", "skills", "experience", "projects", "education"],
    },
    "systems": {
        "label": "🔐 Systems / Security",
        "accent": HexColor("#0f766e"),
        "accent_hex": "#0f766e",
        "header_bg": HexColor("#134e4a"),
        "section_order": ["profile", "experience", "skills", "projects", "education"],
    },
}

# Courses → implied technical skills
COURSE_SKILL_MAP: dict[str, list[str]] = {
    "Machine Learning":                   ["Python", "Scikit-learn", "NumPy", "Pandas"],
    "Deep Learning":                      ["PyTorch", "TensorFlow", "CUDA", "Python"],
    "Artificial Intelligence":            ["Python", "Search Algorithms", "Logic"],
    "Natural Language Processing":        ["Python", "HuggingFace", "NLP", "BERT"],
    "Computer Vision":                    ["OpenCV", "PyTorch", "Python", "CNNs"],
    "Algorithms and Data Structures":     ["Python", "Java", "Algorithm Design", "Complexity Analysis"],
    "Introduction to Programming":        ["Python", "Java", "OOP"],
    "Software Engineering":               ["Git", "CI/CD", "Agile", "Testing"],
    "Database Systems":                   ["SQL", "PostgreSQL", "Database Design"],
    "Computer Networks":                  ["TCP/IP", "Linux", "Network Security"],
    "Operating Systems":                  ["Linux", "C", "Systems Programming"],
    "Distributed Systems":                ["Docker", "Kubernetes", "Go", "gRPC"],
    "Cloud Computing":                    ["AWS", "GCP", "Docker", "Terraform"],
    "Web Development":                    ["JavaScript", "React", "HTML/CSS", "REST APIs"],
    "Linear Algebra":                     ["MATLAB", "NumPy", "Linear Algebra"],
    "Analysis":                           ["Mathematical Analysis", "Calculus"],
    "Probability Theory":                 ["Statistics", "R", "Probability"],
    "Optimization":                       ["Convex Optimization", "Python", "SciPy"],
    "Stochastic Processes":               ["R", "Statistics", "Simulation"],
    "Digital Design":                     ["VHDL", "FPGA", "Digital Logic"],
    "Embedded Systems":                   ["C", "C++", "ARM", "RTOS", "Microcontrollers"],
    "Signal Processing":                  ["MATLAB", "DSP", "Python"],
    "Control Systems":                    ["MATLAB/Simulink", "Control Theory"],
    "Computer Architecture":              ["C", "Assembly", "Hardware Design"],
    "Cryptography":                       ["Python", "Security Protocols", "OpenSSL"],
    "Robotics":                           ["ROS", "Python", "C++", "Sensors"],
}

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class WorkExperience:
    company: str
    role: str
    period: str
    location: str = ""
    bullets: list[str] = field(default_factory=list)


@dataclass
class Education:
    institution: str
    degree: str
    period: str
    grade: str = ""
    notes: str = ""


@dataclass
class Project:
    name: str
    description: str
    technologies: str = ""
    link: str = ""


@dataclass
class CVData:
    name: str
    email: str
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""
    summary: str = ""
    direction: str = "ml"
    education: list[Education] = field(default_factory=list)
    experience: list[WorkExperience] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    languages: list[tuple[str, str]] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Direction detection
# ---------------------------------------------------------------------------

def detect_direction(courses: list[str], grades: dict[str, float]) -> str:
    """Score each career direction from enrolled courses and grades."""
    from tum_pulse.agents.advisor import GRADE_DIRECTION_BOOST, DIRECTION_KEYWORDS

    scores: dict[str, float] = {d: 0.0 for d in DIRECTION_THEMES}

    for course, directions in GRADE_DIRECTION_BOOST.items():
        if any(course.lower() in c.lower() for c in courses):
            grade = grades.get(course, 3.0)
            boost = max(0.1, (4.0 - grade) / 3.0)   # better grade = bigger boost
            for d in directions:
                scores[d] = scores.get(d, 0.0) + boost

    for course in courses:
        course_lower = course.lower()
        for direction, keywords in DIRECTION_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw in course_lower)
            scores[direction] = scores.get(direction, 0.0) + hits * 0.5

    return max(scores, key=lambda d: scores[d])


def suggest_skills(courses: list[str]) -> list[str]:
    """Return deduplicated skill suggestions from the course list."""
    seen: set[str] = set()
    result: list[str] = []
    for course in courses:
        for mapped_course, skills in COURSE_SKILL_MAP.items():
            if mapped_course.lower() in course.lower():
                for skill in skills:
                    if skill not in seen:
                        seen.add(skill)
                        result.append(skill)
    return result


# ---------------------------------------------------------------------------
# Style helpers
# ---------------------------------------------------------------------------

def _make_styles(accent: HexColor) -> dict[str, ParagraphStyle]:
    return {
        "name": ParagraphStyle(
            "name", fontSize=22, leading=26, textColor=white,
            fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=2,
        ),
        "contact": ParagraphStyle(
            "contact", fontSize=8.5, leading=12, textColor=HexColor("#e0e0e0"),
            fontName="Helvetica", alignment=TA_CENTER, spaceAfter=0,
        ),
        "section": ParagraphStyle(
            "section", fontSize=10, leading=13, textColor=accent,
            fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=2,
        ),
        "job_title": ParagraphStyle(
            "job_title", fontSize=9.5, leading=13, textColor=HexColor("#111111"),
            fontName="Helvetica-Bold", spaceAfter=1,
        ),
        "job_meta": ParagraphStyle(
            "job_meta", fontSize=8.5, leading=12, textColor=HexColor("#555555"),
            fontName="Helvetica", spaceAfter=2,
        ),
        "bullet": ParagraphStyle(
            "bullet", fontSize=8.5, leading=12.5, textColor=black,
            fontName="Helvetica", leftIndent=10, spaceAfter=2,
        ),
        "body": ParagraphStyle(
            "body", fontSize=8.5, leading=12.5, textColor=black,
            fontName="Helvetica", spaceAfter=3, alignment=TA_LEFT,
        ),
    }


def _hr(accent: HexColor) -> HRFlowable:
    return HRFlowable(width="100%", thickness=0.8, color=accent, spaceAfter=4, spaceBefore=1)


def _two_col(left: Paragraph, right: Paragraph, right_w: float = 55 * mm) -> Table:
    t = Table([[left, right]], colWidths=[CONTENT_W - right_w, right_w])
    t.setStyle(TableStyle([
        ("ALIGN",         (0, 0), (0, 0), "LEFT"),
        ("ALIGN",         (1, 0), (1, 0), "RIGHT"),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _header_block(data: CVData, theme: dict, s: dict) -> list:
    """Coloured header band with name + contact — fits within content width."""
    bg = theme["header_bg"]
    contact_parts = [p for p in [
        data.email, data.phone, data.location,
        data.linkedin, data.github, data.website,
    ] if p]
    contact_str = "  ·  ".join(contact_parts) if contact_parts else ""

    header_table = Table(
        [[Paragraph(data.name or "Your Name", s["name"])],
         [Paragraph(contact_str, s["contact"])]],
        colWidths=[CONTENT_W],          # must fit within content area
    )
    header_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), bg),
        ("LEFTPADDING",   (0, 0), (-1, -1), 14),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
        ("TOPPADDING",    (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return [header_table, Spacer(1, 8)]


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def _render_profile(data: CVData, theme: dict, s: dict) -> list:
    if not data.summary:
        return []
    return [
        Paragraph("PROFILE", s["section"]),
        _hr(theme["accent"]),
        Paragraph(data.summary, s["body"]),
        Spacer(1, 4),
    ]


def _render_experience(data: CVData, theme: dict, s: dict) -> list:
    if not data.experience:
        return []
    out = [Paragraph("EXPERIENCE", s["section"]), _hr(theme["accent"])]
    for exp in data.experience:
        right = f"{exp.location}  |  {exp.period}" if exp.location else exp.period
        out.append(_two_col(
            Paragraph(f"<b>{exp.role}</b>  —  {exp.company}", s["job_title"]),
            Paragraph(right, s["job_meta"]),
        ))
        for b in exp.bullets:
            if b.strip():
                out.append(Paragraph(f"• {b.strip()}", s["bullet"]))
        out.append(Spacer(1, 5))
    return out


def _render_education(data: CVData, theme: dict, s: dict) -> list:
    if not data.education:
        return []
    out = [Paragraph("EDUCATION", s["section"]), _hr(theme["accent"])]
    for edu in data.education:
        right = f"Grade: {edu.grade}  |  {edu.period}" if edu.grade else edu.period
        out.append(_two_col(
            Paragraph(f"<b>{edu.degree}</b>", s["job_title"]),
            Paragraph(right, s["job_meta"]),
        ))
        out.append(Paragraph(edu.institution, s["job_meta"]))
        if edu.notes:
            out.append(Paragraph(edu.notes, s["body"]))
        out.append(Spacer(1, 5))
    return out


def _render_skills(data: CVData, theme: dict, s: dict) -> list:
    if not data.skills and not data.languages:
        return []
    out = [Paragraph("SKILLS &amp; LANGUAGES", s["section"]), _hr(theme["accent"])]
    skill_str = "  ·  ".join(data.skills) if data.skills else ""
    lang_str  = "  ·  ".join(
        f"<b>{lg}</b> ({lv})" for lg, lv in data.languages
    ) if data.languages else ""

    if data.skills and data.languages:
        t = Table(
            [[Paragraph(f"<b>Technical:</b>  {skill_str}", s["body"]),
              Paragraph(f"<b>Languages:</b>  {lang_str}", s["body"])]],
            colWidths=[CONTENT_W * 0.58, CONTENT_W * 0.42],
        )
        t.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        out.append(t)
    elif data.skills:
        out.append(Paragraph(f"<b>Technical:</b>  {skill_str}", s["body"]))
    else:
        out.append(Paragraph(f"<b>Languages:</b>  {lang_str}", s["body"]))
    out.append(Spacer(1, 5))
    return out


def _render_projects(data: CVData, theme: dict, s: dict) -> list:
    if not data.projects:
        return []
    out = [Paragraph("PROJECTS", s["section"]), _hr(theme["accent"])]
    for proj in data.projects:
        title = proj.name
        if proj.link:
            title += f'  <font color="{theme["accent_hex"]}" size="8">({proj.link})</font>'
        out.append(Paragraph(title, s["job_title"]))
        if proj.technologies:
            out.append(Paragraph(f"<i>{proj.technologies}</i>", s["job_meta"]))
        if proj.description:
            out.append(Paragraph(proj.description, s["body"]))
        out.append(Spacer(1, 5))
    return out


_SECTION_RENDERERS = {
    "profile":    _render_profile,
    "experience": _render_experience,
    "education":  _render_education,
    "skills":     _render_skills,
    "projects":   _render_projects,
}

# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------

def generate_pdf(data: CVData) -> bytes:
    """Build a themed professional PDF CV and return raw bytes."""
    theme = DIRECTION_THEMES.get(data.direction, DIRECTION_THEMES["ml"])
    s = _make_styles(theme["accent"])

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=10 * mm, bottomMargin=14 * mm,
    )

    story: list = _header_block(data, theme, s)

    for section in theme["section_order"]:
        renderer = _SECTION_RENDERERS.get(section)
        if renderer:
            story.extend(renderer(data, theme, s))

    doc.build(story)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Email sender
# ---------------------------------------------------------------------------

def send_cv_email(
    *,
    smtp_host: str,
    smtp_port: int,
    sender_email: str,
    sender_password: str,
    recipient_email: str,
    recipient_name: str,
    applicant_name: str,
    cover_text: str,
    pdf_bytes: bytes,
    pdf_filename: str,
) -> None:
    """Send the CV PDF as an email attachment via STARTTLS SMTP."""
    msg = MIMEMultipart()
    msg["From"]    = sender_email
    msg["To"]      = recipient_email
    msg["Subject"] = f"Application — {applicant_name}"

    body = cover_text or f"Dear {recipient_name},\n\nPlease find my CV attached.\n\nBest regards,\n{applicant_name}"
    msg.attach(MIMEText(body, "plain"))

    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename=pdf_filename)
    msg.attach(attachment)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
        server.ehlo()
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipient_email, msg.as_string())
