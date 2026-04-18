# TUM Easy — Campus Co-Pilot for TUM 🎓

TUM Easy is a multi-agent AI assistant designed to unify and simplify the fragmented digital ecosystem at the Technical University of Munich (TUM).

It connects platforms like **TUMonline**, **Moodle**, **ZHS**, and **Confluence / Collab Wiki** into a single intelligent interface that can retrieve information, recommend actions, and automate repetitive student tasks.

---

## 🚀 Why TUM Easy?

TUM students rely on multiple disconnected systems:

- **TUMonline** → courses, exams, registrations  
- **Moodle** → lecture materials and deadlines  
- **ZHS** → sports course booking  
- **Collab Wiki / Confluence** → project/course documentation  

This leads to:
- missed deadlines  
- inefficient manual checking  
- scattered information  
- unnecessary stress  

**TUM Easy solves this by acting as a personal campus co-pilot.**

---

## 🧠 Core Features

### 📅 Deadline Watcher
Aggregates deadlines from:
- TUMonline
- Moodle
- Confluence

Features:
- unified deadline view  
- SQLite caching  
- course-based filtering  
- upcoming alerts  

---

### 📚 Elective Advisor
Recommends electives using AI.

Features:
- TUM module API integration  
- semantic matching via embeddings  
- personalized suggestions based on profile and grades  

---

### 🧠 Learning Buddy
Helps you study smarter.

Features:
- downloads Moodle PDFs  
- extracts lecture content  
- analyzes past exams  
- generates structured study plans  

---

### 🏃 ZHS Sports Assistant
Automates sport course interaction.

Features:
- search ZHS courses  
- display available slots  
- attempt registration via automation  

---

### 💬 Conversational Interface
Single chat interface powered by multi-agent system.

Agents:
- Watcher → deadlines  
- Advisor → electives  
- Learning Buddy → studying  
- Executor → actions (ZHS)  
- General Assistant → fallback  

---

## 🏗 Architecture

User → Streamlit UI → LangGraph Orchestrator → Agents → External Systems → SQLite

---

## 🛠 Tech Stack

**Frontend**
- Streamlit

**Backend**
- Python 3.10+

**AI**
- Amazon Bedrock (Claude)
- Amazon Titan Embeddings

**Agents**
- LangGraph
- LangChain components

**Automation & Data**
- Playwright
- Requests / BeautifulSoup
- PyMuPDF

**Storage**
- SQLite

---

## 📁 Project Structure

```
tum_pulse/
├── main.py
├── agents/
├── connectors/
├── memory/
├── tools/
```

---

## ⚙️ Setup

### 1. Clone repo
```bash
git clone <repo-url>
cd <repo>
```

### 2. Create environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Install Playwright
```bash
playwright install
```

---

## 🔐 Environment Variables

Create `.env` file:

```
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

```bash
streamlit run tum_pulse/main.py
```

---

## ⚠️ Current Status

Working:
- multi-agent routing  
- Streamlit UI  
- elective recommendations  
- deadline aggregation  
- study plan generation  

Partial / fallback:
- some APIs use mock data  
- scraping depends on login/session  
- ZHS automation may require setup  

---

## 🚧 Limitations

- depends on external platform stability  
- login flows may change  
- requires valid credentials  
- automation is environment-dependent  

---

## 🔮 Future Work

- calendar integration  
- Mensa API  
- room finder  
- push notifications  
- improved personalization  

---

## 🧪 Hackathon Context

Built as part of a Campus Co-Pilot challenge:

> Students should not have to behave like APIs between university systems.

---

## ⚠️ Responsible Use

- do not abuse university systems  
- protect credentials  
- respect platform limits  
