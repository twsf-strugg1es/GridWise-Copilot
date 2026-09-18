# GridWise Copilot

LLM-assisted operator directive interpretation and 24-hour campus energy
optimization. BUP CSE Fest 2026 Hackathon — Online Preliminary.

An operator note in plain English is interpreted by a language model into a
structured directive, validated by deterministic guardrails, and applied as a
constraint to a linear program that returns a 24-hour schedule.

## Quickstart (clean machine)

```bash
git clone https://github.com/twsf-strugg1es/GridWise-Copilot.git
cd GridWise-Copilot

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env               # then add your key, see Configuration
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Verify:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

## Configuration

Create `.env` in the repository root:

```
OPENROUTER_API_KEY=your-key-here
```

| Variable | Required | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | yes | Key for OpenRouter, used for operator-note interpretation |

**Model / provider:** OpenRouter (`https://openrouter.ai/api/v1`), model
`qwen/qwen3-8b`, called at `temperature=0` and instructed to return JSON only.
Configured in `backend/llm/client.py`.

No key is committed to this repository, baked into the Docker image, or written
to logs. `.env` is gitignored.

## Architecture

```
POST /optimize-energy
        |
        v
  backend/api/schemas.py     request validation
        |
        v
  backend/llm/client.py      OpenRouter chat-completions client
  backend/llm/prompts.py     directive-extraction prompt
  backend/llm/parser.py      note -> structured directive
        |
        v
  backend/validator/guardrails.py    deterministic validation of LLM output
        |                            (nothing reaches the optimizer unvalidated)
        v
  optimizer/model.py         LP construction
  optimizer/constraints.py   energy balance, battery rules, directive constraints
  optimizer/solver.py        CBC solve, plan extraction
        |
        v
  24-hour schedule
```

The language model performs the operator-note interpretation. Its output is
treated as untrusted and is validated deterministically before any directive is
turned into an optimization constraint.

| Path | Role |
|---|---|
| `backend/main.py` | FastAPI application |
| `backend/api/routes.py` | `/health` and `/optimize-energy` |
| `backend/api/schemas.py` | Request and response models |
| `backend/llm/` | Client, prompt, and note parser |
| `backend/validator/guardrails.py` | Validation gate for LLM output |
| `optimizer/` | LP model, constraints, solver |
| `frontend/` | Vite + React UI (not required by the judge harness) |
| `tests/` | pytest suite |

## Testing

```bash
pytest -q
```

To exercise the API against a sample scenario, with the service running:

```bash
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d @sample_case.json
```

## Docker

```bash
docker build -t gridwise-copilot:1.0.0 .
docker run --rm -p 8000:8000 -e OPENROUTER_API_KEY=your-key gridwise-copilot:1.0.0
curl http://localhost:8000/health
```

The image exposes port 8000, binds `0.0.0.0`, and contains no credentials.

## Dependencies and credits

| Package | Use |
|---|---|
| FastAPI + Uvicorn | HTTP service and ASGI server |
| Pydantic | Request and response validation |
| PuLP (bundled CBC) | Linear programming |
| openai | OpenRouter chat-completions client |
| pytest | Tests |
| React + Vite | Frontend UI |

Versions are pinned in `requirements.txt`. AI coding assistance was used during
development; the architecture and optimization model are the team's own work.

## Known limitations

- The request and response schemas do not yet match the Problem Statement
  contract in every field. See the open pull request for a version that does.
- One operator note is interpreted per request; the specification allows 1–3.
- `node_modules/` is currently tracked in the repository and should be removed
  from version control.
