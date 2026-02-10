# Repository Guidelines

## Project Structure & Module Organization
- `robot_project/` is the main Python app. Entry points: `src/brain/brain.py` (text chat + memory), `main_voice.py` (voice pipeline), and `view_memory.py` (inspect memory store).
- `robot_project/src/brain/` holds LLM orchestration and memory logic; `robot_project/src/voice/` holds ASR/VAD/TTS and audio device control.
- `robot_project/config/` contains local JSON config (`api.json`, `persona.json`, `speech.json`).
- `robot_project/data/` stores runtime memory data and is ignored by git; `docs/` contains setup and deployment guides.
- `bidirection.py` is a root-level utility script.

## Build, Test, and Development Commands
Install dependencies and create a local virtual environment:
```bash
cd robot_project
python -m venv venv
pip install -r requirements.txt
```
Activate the venv (PowerShell example):
```bash
.\venv\Scripts\Activate.ps1
```
Run core flows:
```bash
python src/brain/brain.py            # text chat + memory
python src/brain/brain.py --backend ollama
python main_voice.py                 # voice chat (needs audio device + speech.json)
python view_memory.py                # inspect stored memories
```

## Coding Style & Naming Conventions
- Python 3.11+, 4-space indentation, and PEP 8 style.
- Use `snake_case` for modules/functions/variables and `CapWords` for classes.
- Keep brain-related logic in `src/brain/` and audio pipelines in `src/voice/`.
- No formatter or linter is configured; keep changes small and readable.

## Testing Guidelines
- No automated test suite is configured yet. Use manual smoke checks:
  - `python src/brain/brain.py` for text flow and memory recall.
  - `python main_voice.py` for voice flow if audio hardware is available.
- If you add tests, place them under `robot_project/tests/` with `test_*.py` names (suggest `pytest`). No coverage threshold is enforced.

## Commit & Pull Request Guidelines
- Commit history uses conventional prefixes like `feat:`, `docs:`, and `build:`. Follow that pattern and keep summaries concise.
- PRs should include: a clear description, exact test commands run, and notes on config or hardware impact.
- Update `docs/` when behavior or setup steps change.

## Security & Configuration Tips
- Do not commit API keys in `robot_project/config/api.json`; use local values only and redact logs.
- Keep `robot_project/data/` local; it is runtime state and should not enter version control.
