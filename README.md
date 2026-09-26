# ClassroomInsight — Intelligent Multi-Agent Teaching & Learning Ecosystem

A multi-agent educational intelligence platform built with **Three.js**, **HTML/CSS/JS**, and **Python LLM Multi-Agents (Gemini 3.5 & Groq)**.

---

## 🚀 How to Run the Entire Application (Frontend + Backend)

### Single Command Execution
In your VS Code terminal (from the project root `ARG` folder):

```powershell
python server.py 3000
```

Once running, access the following in your browser:
- **3D Landing Page & Multi-Agent Portal**: [http://localhost:3000](http://localhost:3000)
- **Teacher Intelligence Dashboard**: [http://localhost:3000/dashboard](http://localhost:3000/dashboard)
- **Multi-Agent System Health & API Status**: [http://localhost:3000/api/status](http://localhost:3000/api/status)
- **Live Classroom Insights & Root-Cause Telemetry**: [http://localhost:3000/api/classroom/insights](http://localhost:3000/api/classroom/insights)

---

## 🏗 System Architecture & Integrations

### 1. Frontend Layer
- **3D WebGL Hero Portal ([index.html](file:///c:/Users/A%20S%20Nemitha/Desktop/ARG/index.html))**:
  - Full-screen animated 3D mesh & particle field in Three.js with mouse parallax and warm-to-cool amber lighting.
  - Floating Code/API Card with live tab switching and **"⚡ Run Live"** button calling the Python agent backend.
  - Quick-preview modal and direct links to the Teacher Portal.
  - **Raah Analytics** script integrated.
- **Teacher Dashboard ([person-c-classroom/dashboard.html](file:///c:/Users/A%20S%20Nemitha/Desktop/ARG/person-c-classroom/dashboard.html))**:
  - Comprehensive classroom intelligence interface: Misconception clusters, False Mastery watchlist, Question Ambiguity quality ratings, and Learning Loop visualization.
  - **Raah Analytics** script integrated.

### 2. Backend & Agent Core (Python)
- **Unified Server ([server.py](file:///c:/Users/A%20S%20Nemitha/Desktop/ARG/server.py))**:
  - Handles static file serving, CORS, and REST API routing for all agents.
- **Personalized Practice Core Agents ([person-b-core-agents/](file:///c:/Users/A%20S%20Nemitha/Desktop/ARG/person-b-core-agents))**:
  - `loop_controller.py`: Manages closed-loop transitions (`diagnosed -> intervened -> verifying -> verified / escalated`).
  - `recommender_agent.py`: Generates targeted interventions via Gemini & Groq LLMs.
  - `verification_agent.py`: Generates transfer-based probes and classifies genuine vs. surface mastery.
  - `llm_client.py`: Dual-provider fallback with Gemini 3.5 and Groq.
- **Classroom Insights ([person-c-classroom/](file:///c:/Users/A%20S%20Nemitha/Desktop/ARG/person-c-classroom))**:
  - `classroom_insight_agent.py`: Aggregates student states into ranked misconception clusters.
  - `root_cause_agent.py`: Identifies downstream topic impact using reverse traversal of `prereq_graph.json`.
  - `assessment_quality_agent.py`: Flags ambiguous or misleading quiz questions.

---

## 🔑 Environment Variables
Your `.env` file in the root directory configures your AI credentials:
```ini
GROQ_API_KEY=your_groq_key_here
GEMINI_API_KEY=your_gemini_key_here
```
*(Securely excluded via `.gitignore`)*
