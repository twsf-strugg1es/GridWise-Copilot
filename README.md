# GridWise Copilot

LLM-assisted operator directive interpretation and 24-hour campus energy optimization.
BUP CSE Fest 2026 Hackathon — Online Preliminary.

The service reads 1–3 plain-English operator notes, converts each into a strict
machine-checkable directive, validates every directive deterministically, applies
the survivors to a linear program, and returns the cheapest valid 24-hour
schedule.

---

## Quickstart (clean machine, ~2 minutes)

```bash
git clone https://github.com/twsf-strugg1es/GridWise-Copilot.git
cd GridWise-Copilot

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env               # then set LLM_API_KEY (see Configuration)

uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Verify:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Run one public sample end to end:

```bash
python - <<'PY'
import json, httpx
case = json.load(open("tests/public_sample_cases.json"))["cases"][0]["input"]
r = httpx.post("http://localhost:8000/optimize-energy", json=case, timeout=35)
print(r.status_code)
print(json.dumps(r.json()["directive_interpretation"], indent=2))
print("total_cost_bdt:", r.json()["total_cost_bdt"])
PY
```

Run **all ten** public samples and grade them the way the judge would:

```bash
python scripts/run_samples.py --offline    # optimizer only, no API key needed
python scripts/run_samples.py              # full pipeline, in-process
python scripts/run_samples.py --url http://localhost:8000
pytest -q                                  # 43 tests
```

Expected on all three modes:

```
valid schedules      : 10/10
interpretation match : 10/10
optimization quality : 1.0000  -> 10.00/10 points
```

---

## Configuration

Every variable is documented inline in [`.env.example`](.env.example). No secret
is committed, baked into the image, or logged.

| Variable | Default | Purpose |
|---|---|---|
| `LLM_API_KEY` | — | **Required.** Key for an OpenAI-compatible chat-completions endpoint. `OPENAI_API_KEY` is also accepted. |
| `LLM_BASE_URL` | OpenAI | Point at any OpenAI-compatible provider: Groq, OpenRouter, Together, or a local Ollama at `http://localhost:11434/v1`. |
| `LLM_MODEL` | `gpt-4o-mini` | Model id as the provider names it. |
| `LLM_TIMEOUT_SECONDS` | `20` | Per-call timeout, kept under the judge's 30s request budget. |
| `LLM_MAX_ATTEMPTS` | `2` | Attempt 2 is a repair attempt fed the guardrail's own rejection message. |
| `ALLOW_HEURISTIC_FALLBACK` | `1` | If the provider is unreachable, answer from the heuristic backstop instead of failing the request. |
| `LOG_LEVEL` | `INFO` | |

**Model/provider used for submission:** OpenAI-compatible chat completions,
`LLM_MODEL` as configured at deploy time (default `gpt-4o-mini`), called with
`temperature=0` and JSON response mode.

---

## Architecture

```
                 ┌──────────────────────────────────────────────────┐
  POST           │ 1. REQUEST SCHEMA          backend/api/schemas.py│
  /optimize-     │    24 hours, 1–3 notes, battery — else HTTP 400   │
  energy         └──────────────────────┬───────────────────────────┘
                                        ▼
                 ┌──────────────────────────────────────────────────┐
                 │ 2. LLM INTERPRETATION      backend/llm/parser.py  │
                 │    ONE call for all notes, temperature 0,         │
                 │    JSON mode, few-shot with paraphrases           │
                 └──────────────────────┬───────────────────────────┘
                                        ▼
                 ┌──────────────────────────────────────────────────┐
                 │ 3. DETERMINISTIC GUARDRAILS                       │
                 │    backend/validator/guardrails.py                │
                 │    type ∈ six · one entry per note · hours unique │
                 │    ints 0–23 ascending · 0 ≤ factor ≤ 1 ·         │
                 │    reserve ≤ capacity · applies semantics         │
                 │    FAIL → one repair attempt → heuristic fallback │
                 └──────────────────────┬───────────────────────────┘
                                        ▼
                 ┌──────────────────────────────────────────────────┐
                 │ 4. OPTIMIZER               optimizer/*.py         │
                 │    directives → LP bounds → CBC → net & replay    │
                 └──────────────────────┬───────────────────────────┘
                                        ▼
                             valid, cheapest 24-hour plan
```

| Path | Role |
|---|---|
| `backend/api/schemas.py` | Request/response contract. Structural rejection happens here, before a token is spent. |
| `backend/llm/prompts.py` | System prompt and few-shot examples. Paraphrases the same directive several ways on purpose. |
| `backend/llm/parser.py` | One model call per scenario, guardrail-gated, one repair retry, note-set cache. |
| `backend/llm/fallback.py` | Heuristic backstop. **Not** the interpretation path — see below. |
| `backend/validator/guardrails.py` | The only gate between the model and the optimizer. |
| `optimizer/constraints.py` | Directives → per-hour effective solar, reserve floor, forbidden windows, grid caps. |
| `optimizer/model.py` | Builds the LP. |
| `optimizer/solver.py` | Solves, nets the battery to one action per hour, replays state forward. |
| `scripts/replay.py` | Independent re-implementation of the judge's checks. |
| `scripts/run_samples.py` | Grades all ten public cases. |

### The LLM is in the interpretation path

`directive_interpretation` — the object the optimizer's constraints are built
from — is produced by the language model. `plan_summary` is generated
deterministically and carries no interpretation weight, so the mandatory-LLM
requirement is satisfied by the part that actually matters.

`backend/llm/fallback.py` is a **secondary** path that runs only after the model
has failed all its attempts and only when `ALLOW_HEURISTIC_FALLBACK=1`. It exists
so a provider outage produces a degraded answer rather than a 500. It is
deliberately conservative: anything it cannot read confidently becomes `no_op`
rather than an invented constraint.

---

## Design notes

**The two rules that cause most wrong answers.** Time windows are start-inclusive
and end-exclusive, so 1 PM–3 PM is `[13, 14]`. And `factor` is the fraction of
solar that *remains*, so an 80% reduction is `0.2`. Both are stated twice in the
prompt and enforced again in the guardrails.

**Charge and discharge are separate LP variables**, because the hourly rate limits
differ per direction. The cost is that a degenerate optimum may set both non-zero
in the same hour — there is no round-trip loss in this problem, so the solver is
never penalised for it — while the response schema allows exactly one action.
`_net_battery` collapses them. That is safe by construction: replacing `(c, d)`
with `(c-d, 0)` or `(0, d-c)` leaves both the energy balance and the state
transition unchanged, and the surviving magnitude is no larger than the original
in that direction, so its rate limit still holds.

**The printed plan is made self-consistent, not merely close.** The judge replays
the numbers we print, so after the solve the values are rounded once, `grid_kwh`
is recomputed from the energy-balance equation, and battery energy is replayed
forward from the stated initial level. Accumulated drift lands near 1e-5, two
orders below the 0.01 tolerance.

**CBC is warmed at startup.** Its first solve in a process costs ~5 s and every
later one ~25 ms. Without the warm-up the judge's first hidden case would pay it.

**Failure is controlled at three levels.** Bad request → 400 with field detail.
Bad model output → one repair attempt, then the heuristic backstop. Infeasible
constrained LP → solve without directives, then a naive grid-only plan that is
always valid. Unhandled exception → 500 with no stack trace and nothing from the
environment.

---

## Docker fallback

```bash
docker build -t gridwise-copilot:1.0.0 .
docker run --rm -p 8000:8000 -e LLM_API_KEY=sk-your-key gridwise-copilot:1.0.0
curl http://localhost:8000/health
```

The image exposes port 8000, binds `0.0.0.0`, contains no credentials, and
carries a `HEALTHCHECK` against `/health`. Add `-e LLM_BASE_URL=...` and
`-e LLM_MODEL=...` for a non-OpenAI provider.

---

## API

### `GET /health`

```json
{"status": "ok"}
```

### `POST /optimize-energy`

Request (abbreviated — 24 hour entries required):

```json
{
  "scenario_id": "GRID-101",
  "operator_notes": [
    "Solar output will drop to about 20% from 1 PM to 3 PM.",
    "The cafeteria menu changes tomorrow."
  ],
  "hours": [{"hour": 0, "demand_kwh": 180, "solar_kwh": 0, "tariff_bdt_per_kwh": 7}],
  "battery": {
    "capacity_kwh": 500, "initial_energy_kwh": 200, "minimum_energy_kwh": 50,
    "max_charge_kwh_per_hour": 100, "max_discharge_kwh_per_hour": 100
  }
}
```

Response (abbreviated):

```json
{
  "scenario_id": "GRID-101",
  "directive_interpretation": [
    {"note_index": 0, "applies": true, "directive_type": "solar_reduction",
     "structured_adjustment": {"hours": [13, 14], "factor": 0.2},
     "explanation": "Solar availability is reduced during the maintenance window."},
    {"note_index": 1, "applies": false, "directive_type": "no_op",
     "structured_adjustment": null,
     "explanation": "This note does not affect today's energy schedule."}
  ],
  "hourly_plan": [
    {"hour": 0, "grid_kwh": 180.0, "solar_used_kwh": 0.0,
     "battery_action": "idle", "battery_kwh": 0.0, "battery_energy_after_kwh": 200.0}
  ],
  "total_grid_kwh": 2692.5,
  "total_cost_bdt": 38365.0,
  "peak_grid_kwh": 175.0,
  "plan_summary": "Applied 1 operator directive (solar_reduction); 1 note was unrelated to energy and ignored. ..."
}
```

Status codes: `200` success · `400` malformed or structurally invalid request ·
`500` controlled internal error, no stack trace.

---

## Testing

```bash
pytest -q                                  # 43 tests: guardrails, optimizer, API contract
python scripts/run_samples.py --offline    # all 10 public cases, no API key required
python scripts/run_samples.py --verbose    # full pipeline with per-violation detail
```

`scripts/replay.py` re-implements the judge's checks from the Problem Statement
rather than importing the service, so a bug in the optimizer cannot hide behind
the same bug in the checker. It verifies the energy balance every hour, battery
transitions, bounds and rate limits, effective-solar ceilings, every directive
type against organizer ground truth, end-of-day neutrality, and that the reported
totals match a recalculation from `hourly_plan`.

---

## Dependencies and credits

| Package | Use |
|---|---|
| [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) | HTTP service and ASGI server |
| [Pydantic](https://docs.pydantic.dev/) | Request/response validation |
| [PuLP](https://coin-or.github.io/pulp/) (bundled CBC) | Linear programming |
| [openai](https://github.com/openai/openai-python) | OpenAI-compatible chat-completions client |
| [httpx](https://www.python-httpx.org/) | HTTP client used by the sample runner |
| [pytest](https://docs.pytest.org/) | Tests |

Versions are pinned in `requirements.txt` so the Docker image and a local
reproduction build the tree that was tested. AI coding assistance was used during
development; the architecture, the guardrail rules and the optimization model are
the team's own work.

---

## Known limitations

- **Overlapping directives of the same type resolve to the stricter one.** Two
  `max_grid_window` directives over the same hour take the lower cap; two
  `solar_reduction` directives take the smaller remaining factor. The Problem
  Statement does not specify this case.
- **A directive with no stated time window is read as all 24 hours.** Reasonable,
  but a guess.
- **The heuristic fallback is weaker than the LLM** on unseen paraphrases, by
  design. It is a reliability backstop, not a second interpreter.
- **The LP has no round-trip battery efficiency**, because the Problem Statement
  defines none. If a hidden case implied one, the plans would be optimistic.
- **`no_op` notes that also contain an energy-shaped phrase** ("the generator test
  moves to next month") depend on the model reading the tense. The prompt covers
  it explicitly; the heuristic fallback does not.
