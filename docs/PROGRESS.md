# Progress

| Phase | Status | Where |
|---|---|---|
| 0 Plan + data audit | done (21 Nov) | `docs/PLAN.md`, `docs/DATA_AUDIT.md` |
| 1 Skeleton + loaders | done (21 Nov) | `mira/data/`, `tests/test_*loader*.py`, CI |
| 2 Pricing engine | done (21 Nov) | `mira/pricing/`, `tests/test_pricing.py` |
| 2.5 Thin A2UI slice | done (22 Nov), verified in Chromium | `mira/ui/`, `mira/agent/graph.py`, `frontend/` |
| 3 Retrieval + grounding | done (21 Nov) | `mira/retrieval/` |
| 4 LangGraph agent + guard + flags + CLI | done (22 Nov) | `mira/agent/`, `mira/chat.py` |
| 5 Generative UI | done (22 Nov), desktop + 375px screenshots | `frontend/lib/catalog/`, `docs/screenshots/` |
| 6 Tracing | done; Langfuse connected (US region), local JSON traces without keys | `mira/tracing.py`, `mira/privacy.py` |
| 7 Evals | done; real-LLM run (DeepSeek) + judge + hand-label agreement | `evals/`, `reports/` |
| 7b Fixed problem | done | `docs/FIXED_PROBLEM.md` |
| 8 Enquiries, staff page, returning visitors | done | `mira/api.py`, `frontend/app/staff/` |
| 9 AI content + approval | done | `mira/content_agent.py` |
| 10 Submission package | done except the video and the final LLM run | `README.md`, `docs/DEMO_SCRIPT.md`, `docs/DEMO_VIDEO_PLAN.md` |
| UI redesign (25 Nov) | done: Inter, side panel, welcome starters, text before cards, 320px cards, tour shelf, itinerary days, staff tiles | `frontend/`, `docs/SYSTEM_REVIEW.md` |
| Real-LLM round (25 Nov) | done: DeepSeek provider, 5 behaviour bugs found by the model run and judge, fixed with tests | `mira/llm.py`, `docs/FIXED_PROBLEM.md` |
| Bonus: model routing, personalisation | done | `mira/llm.py` (`RoutedLLM`), `TourResolver.similar_to` |
| Bonus: MCP server | done | `mira/mcp_server.py`, `tests/test_mcp.py` |

## Latest numbers (25 Nov)
- `pytest`: 272 passed.
- `python -m evals.run` with DeepSeek (`deepseek-flash`, judge `deepseek-v4-pro`): 55/55; golden 18/18; consistency 69/69; invented prices 0; missing/expired 10/10; judge 32/32; 138/138 turns understood by the model.
- Offline baseline (`--offline`): 55/55 (`reports/eval_report_offline.md`).
- `python scripts/adversarial.py` with DeepSeek: 20 attacks, 0 invented amounts.
- Judge vs Shinthurie's labels: 10/10 (`reports/judge_agreement.md`).
- Live margin change rehearsed: consistency stays 100%, golden 4/6 (the two day-tour seeds change, as expected).

## What only Shinthurie can do
1. Record the 5-minute video (`docs/DEMO_VIDEO_PLAN.md`).
2. Push, check CI is green, add Senura as a collaborator on submission day.

### Open questions
- H03 overlapping Peak row: waiting for Senura (currently `conflicting_rate` for 1 Jan to 31 Mar 2027).
- T06: decided (priced as the 1-day tour the rates define, traveller told "no overnight stay", staff flag on every quote). See DATA_AUDIT A13.
