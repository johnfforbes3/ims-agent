# IMS Agent — Phase 1 Proof of Concept

An AI agent that reads an Integrated Master Schedule (IMS), simulates CAM status input, runs critical path analysis and Schedule Risk Assessment (SRA), synthesizes insights via Claude, and produces a structured text report.

## Quick Start

### Prerequisites

- Python 3.11+
- An Anthropic API key

### Setup

```bash
# 1. Clone the repo
git clone https://github.com/johnfforbes3/ims-agent.git
cd ims-agent

# 2. Create and activate a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# 5. Run the agent
python main.py
```

### Running Tests

```bash
pytest tests/ -v
```

## Project Structure

```
ims-agent/
├── agent/
│   ├── core.py           — Orchestrates the full Phase 1 pipeline
│   ├── file_handler.py   — IMS XML parsing and write-back
│   ├── llm_interface.py  — All Anthropic SDK calls (single entry point)
│   ├── sra_runner.py     — Monte Carlo SRA engine
│   └── report_generator.py — Markdown report generation
├── tests/                — pytest test suite (mirrors agent/)
├── data/                 — Sample IMS files (XML; real .mpp files gitignored)
├── reports/              — Generated reports (gitignored)
├── logs/                 — Audit and operational logs (gitignored)
├── docs/                 — Architecture decisions
├── .env.example          — Environment variable template
├── requirements.txt
└── main.py               — Entry point
```

## Phase Status

| Phase | Name | Status |
|---|---|---|
| 1 | Proof of Concept | In Progress |
| 2 | Voice Interview Layer | Not Started |
| 3 | Full Automation Loop | Not Started |
| 4 | Q&A Interface | Not Started |
| 5 | Production Hardening | Not Started |

## Key Design Decisions

See [docs/decisions.md](docs/decisions.md) for full rationale on technology choices.
