# TUM Easy — Campus Co-Pilot for TUM 🎓

TUM Easy is a multi-agent AI assistant that unifies the fragmented digital ecosystem at the Technical University of Munich (TUM).

It connects platforms like **TUMonline**, **Moodle**, **ZHS**, and optional **Confluence/Collab** sources into a single intelligent interface that can:
- retrieve relevant information,
- recommend decisions,
- support studying with real course materials,
- and automate repetitive student workflows.

---

## 🚀 Why TUM Easy?

TUM students constantly switch between disconnected systems:

- **TUMonline** → courses, exams, registrations  
- **Moodle** → lecture materials and deadlines  
- **ZHS** → sports booking  
- **Confluence / Collab** → course or project information  

This fragmentation leads to:
- missed deadlines,
- inefficient manual checking,
- scattered information,
- and unnecessary stress and time loss.

TUM Easy acts as a personal AI co-pilot that centralizes these workflows in one interface.

---

## 🧠 Core Features

### 📅 Deadline Watcher
Aggregates deadlines across platforms and stores them locally for quick retrieval.

Sources:
- TUMonline (NAT API + fallback scraping)
- Moodle (AJAX/API + DOM fallback)
- Confluence / Collab (optional search)

Features:
- unified deadline view
- filtering by enrolled courses
- automatic alert generation
- SQLite persistence
- calendar integration

---

### 🎓 Elective & Career Recommender
Recommends electives based on the student profile and explains why they fit.

Features:
- real TUM module catalogue via NAT API
- semantic matching via Titan embeddings
- profile-aware recommendations using courses and grades
- LLM-generated reasoning via Claude
- career path suggestions and relevant Munich companies

---

### 📚 Smart Learning Buddy
A study assistant that works with real course materials.

Features:
- detects the relevant course from user input
- selects useful documents from cached Moodle materials
- extracts content from PDFs
- analyzes important topics with LLMs
- generates:
  - structured study plans
  - summaries and explanations
  - follow-up study prompts
- adapts to weak subjects and exam relevance

---

### 🏃 ZHS Sports Assistant
Supports interaction with the ZHS system.

Features:
- course search
- availability checks
- experimental automated registration

---

### 📄 CV Builder
Generates a professional, themed, downloadable PDF CV directly from the app — no external tools required.

Features:
- guided multi-step form (personal info, education, work experience, skills, languages, projects)
- **auto-fill from TUM profile** — email, education, and skills pre-populated from your enrolled courses and grades
- **major-based templates** — direction auto-detected from your courses (ML, Software, Mathematics, Electrical, Systems); each has a distinct colour scheme and section ordering optimised for that field
- **skill inference** — enrolled courses mapped to relevant technical skills (e.g. Machine Learning → Python, PyTorch, Scikit-learn)
- **send to company** — pick a Munich company from your career direction, enter the HR email, and the app sends your CV as a PDF attachment via SMTP using your TUM credentials
- generated locally with `reportlab` — no cloud upload, no third-party service

---

### 💬 Conversational Interface
A single chat interface powered by a multi-agent system.

Agents:
- **Watcher** → deadlines
- **Advisor** → electives and career direction
- **Learning Buddy** → studying and course materials
- **Executor** → actions such as ZHS interaction
- **CV Builder** → PDF CV generation from user-provided profile data

---

## 🏗 Architecture

```text
User → Streamlit UI → LangGraph Orchestrator → Agents → External Systems → SQLite
```

### Routing Design
The orchestrator uses **fast heuristic routing** rather than an LLM for intent classification.  
This keeps routing latency low and delegates the actual reasoning to the specialized agents.

Context used for routing includes:
- enrolled courses
- grades
- weak subjects
- upcoming deadlines
- time pressure

---

## 🛠 Tech Stack

### Frontend
- **Streamlit** → interactive web interface and chat UI

### Backend
- **Python 3.10+** → core application logic
- **LangGraph** → orchestration of agent nodes and flow
- **SQLite** → persistent local storage for profiles, deadlines, alerts, and caching

### AI
- **AWS Bedrock**
  - **Claude Haiku** → fast responses and lightweight reasoning
  - **Claude Sonnet** → heavier reasoning and study-plan generation
  - **Titan Embeddings** → semantic similarity for recommendations

### Data & Automation
- **Requests** → TUM NAT API integration
- **Playwright** → browser automation for login-based or dynamic pages
- **PyMuPDF** → PDF parsing for study materials
- **ReportLab** → PDF generation for the CV Builder
- **smtplib** → SMTP email sending for CV delivery (STARTTLS, uses TUM credentials)

### Performance / Caching
- **SQLiteMemory** → structured persistence
- **LLMCache** → cached model outputs to reduce latency and cost
- **Connector cache** → cached Moodle/current-course data

---

## 📁 Project Structure

```text
tum_pulse/
├── agents/
│   ├── advisor.py              # Elective recommendation and career guidance
│   ├── cv_maker.py             # PDF CV generation (reportlab)
│   ├── executor.py             # ZHS and action execution
│   ├── learning_buddy_v2.py    # Smart study assistant
│   ├── orchestrator.py         # LangGraph routing logic
│   └── watcher.py              # Deadline aggregation and alerts
├── connectors/
│   ├── cache.py                # Connector-level caching utilities
│   ├── moodle.py               # Moodle connector
│   └── tumonline.py            # TUMonline connector
├── data/                       # Downloaded or cached study materials
├── memory/
│   └── database.py             # SQLite-based memory layer
├── tools/
│   ├── bedrock_client.py       # AWS Bedrock integration
│   ├── embeddings.py           # Titan embedding utilities
│   ├── llm_cache.py            # Cached LLM responses
│   └── moodle_scraper.py       # Moodle scraping / Playwright fallback
├── config.py                   # Environment variables and paths
├── db.py                       # DB setup helpers
└── main.py                     # Streamlit entry point
```

---

## ⚙️ Setup

### 1. Clone the repository
```bash
git clone <repo-url>
cd <repo>
```

### 2. Create and activate a virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Install Playwright browsers
```bash
python -m playwright install
```

### 5. Create your environment file
```bash
cp .env.example .env
```

### 6. Fill in required credentials
Example variables:

```env
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=

TUM_USERNAME=
TUM_PASSWORD=

ZHS_USERNAME=
ZHS_PASSWORD=

CONFLUENCE_URL=
CONFLUENCE_USERNAME=
CONFLUENCE_PASSWORD=
CONFLUENCE_PAT=
```

---

## ▶️ Run the App

Run from the project root:

```bash
python -m streamlit run tum_pulse/main.py
```

---

## ⚠️ Current Status

### Working
- multi-agent routing with LangGraph
- Streamlit interface
- deadline aggregation
- elective recommendations
- study-plan generation from course materials
- calendar integration

### Partial / fallback
- some platform access paths depend on login/session state
- scraping fallbacks may return partial data
- ZHS automation is still experimental

---

## 🚧 Limitations

- depends on the stability of external university systems
- SSO / login flows may change and break scraping
- valid credentials are required for some features
- Playwright-based automation is environment-dependent
- reasoning-heavy tasks, especially study-plan generation and document analysis, can be slower than simple routing or retrieval tasks

---

## 🔮 Future Work

- smarter notifications and reminders
- Mensa API integration
- room finder / campus navigation support
- improved long-term personalization

---

## 🧪 Hackathon Context

Built in the spirit of a campus co-pilot:

> Students should not have to act as the integration layer between university systems.

---

## ⚠️ Responsible Use

- do not abuse university systems
- protect your credentials
- respect rate limits and platform policies
