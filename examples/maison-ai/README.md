# Maison AI — Your Personal Dining Assistant

A local DevFest hands-on restaurant demo. The UI follows the presentation: Google Sans Flex, `#fbfbfd` background, white/gray rounded panels, Google blue actions and restrained Google color accents.

## Start

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22+, [pnpm](https://pnpm.io/installation).

```powershell
cd examples/maison-ai
python scripts/jobs.py start install
python scripts/jobs.py status install
# After installation completes:
python scripts/dev.py --background
python scripts/dev.py --status
```

Open **http://127.0.0.1:3008**. API and Swagger: http://127.0.0.1:8008/docs.

For a foreground launch: `python scripts/dev.py`. Stop background servers with `python scripts/dev.py --stop`.

## Model providers

Copy `.env.example` to `.env` for a new checkout. `.env` is ignored and is read only by Python. Never use `NEXT_PUBLIC_` for a provider key.

| Provider | Configuration |
| --- | --- |
| Xiaohongshu DOT | `MODEL_PROVIDER=dot`, `DOT_API_KEY`, `DOT_BASE_URL=https://note3-prev-api.askdiandian.com/v1`, `DOT_MODEL=dots3-note-prev` |
| Gemini | `MODEL_PROVIDER=gemini`, `GOOGLE_API_KEY`, optionally `GEMINI_MODEL` |
| Offline fallback | `MODEL_PROVIDER=mock` or launch `python scripts/dev.py --mock` |

DOT uses ADK's `LiteLlm` OpenAI-compatible adapter with the required **`api-key` header**. Thinking is disabled for this interactive demo. Both the primary dining agent and the official secondary A2UI generation tool use the selected provider. A2UI v0.9 is intentionally used throughout; it matches the installed CopilotKit renderer. The presentation's simplified v1.0 example is a separate teaching artifact.

Mock Mode is explicitly labelled. Its scripted `BaseLlm` runs through the real ADK runtime and AG-UI adapter, and its surfaces use the real A2UI renderer. Its decisions and layouts are deterministic fixtures, **not live AI-generated UI**. No automatic fallback silently changes a live request into a mock result.

## Architecture

```text
Next.js / React + CopilotKit
  → AG-UI HttpAgent → FastAPI → ag-ui-adk → ADK Restaurant Agent
      → real business FunctionTools → menu.json / SQLite
      → official get_a2ui_tool → secondary model → A2UI operations
  ← AG-UI TOOL_CALL_RESULT / state snapshots
  → official A2UIProvider + A2UIRenderer + registered React catalog
  → local option/data-model changes → A2UI action → AG-UI → next ADK run
```

CopilotKit is self-managed against the local AG-UI endpoint. The client passes its catalog with the official `buildCatalogContextValue` and schema-context contract. The official ADK A2UI generation/recovery tool consumes that same catalog. The frontend applies operations from actual tool-result events to the official renderer; it does not treat text containing JSON as a rendered surface.

The restaurant catalog composes layout, dish photos/prices/facts, options, quantities and cart controls. It also registers `RecommendationFilters`, `ServingInfo`, `NutritionTotal`, `CalorieControls`, `ReservationForm`, and `ReservationStatus` for the dining workflows. Recommendation cards remain composed from individual A2UI components. The frontend `ask_user` is registered using `useHumanInTheLoop`; ADK sees it through `AGUIToolset`.

## Business rules

- 24 dishes: 4 appetizers, 7 mains, 5 pasta/pizza, 4 desserts, 4 drinks; one sold-out item.
- Dietary filters and actual availability come from `backend/data/menu.json`.
- Prices and cart totals come from backend data and integer cents. The model never supplies a trusted price.
- Cart keys are per-tab session/thread UUIDs. This is a loopback workshop app, not a deployed multi-user authentication system.
- Selecting options and quantities updates local A2UI surface data; Add to cart submits their current values.
- Checkout creates an expiring quote and a fixed A2UI order-review surface. It does not submit an order.
- Confirm Order requires a matching explicit UI action, valid quote, unchanged cart revision, and an idempotency key. Chat alone cannot authorize placement.
- SQLite persists demo orders; GET `/orders/{threadId}` retrieves them. There is no payment, kitchen or delivery integration.
- Unknown actions/options and sold-out dishes are rejected. Components render React content and do not execute generated JavaScript.

## Dining workflows

Open **Agent** to use **Find dishes**, **Reserve a table**, **Calculate calories**, or **Review & checkout**. These buttons request A2UI operations from the backend; the chat agent can call the same business tools. All workflow forms and result cards use the registered A2UI catalog.

- **Recommendations:** filter 1–12 diners, vegetarian/vegan preferences, excluded declared allergens, a calorie limit per person per candidate dish, and a group price limit per candidate dish. Each card shows its real menu image, unit price, suggested portions, serving guidance and energy. Changing quantities updates the card preview; Add to table updates the authoritative cart. These are alternatives, not a combined meal plan. Allergen filters use declared recipe allergens; cross-contact information is unavailable.
- **Calories and checkout:** totals are calculated on the server as recipe kcal × selected portions. The calorie surface shows each line, total energy, and an equal split for the entered diner count. Checkout includes the energy and price totals and retains the explicit Confirm Order gate. Calories are illustrative estimates and exclude customization changes.
- **Reservations:** enter date, start/end time and 1–12 guests. Times use Singapore restaurant time (UTC+08:00). The demo inventory has seven tables with 2, 2, 4, 4, 6, 8 and 12 seats. Check availability, choose a table, and click Confirm Reservation. SQLite checks capacity and overlapping windows atomically when saving; identical confirmation retries are idempotent. These bookings are local demo records, with no external restaurant connection.

Agent tools: `recommend_dishes`, `calculate_total_calories`, `show_reservation`, `check_reservation`, and `reserve_table`, alongside the existing cart and order tools. `GET /reservations/{threadId}` retrieves this session's saved bookings.

## Inspector and workshop

Open **Developer Inspector** to see captured ADK tool calls, actual AG-UI events, latest A2UI operations and server cart state. **View A2UI JSON** switches the main area between protocol data and rendered UI. The logs are live observations, not prewritten event examples.

See [WORKSHOP.md](WORKSHOP.md) for a 5–8 minute walkthrough.

## Checks

```powershell
python scripts/jobs.py start verify
python scripts/jobs.py status verify
# Mock Mode servers must be running for browser tests:
python scripts/dev.py --stop
python scripts/dev.py --mock --background
cd frontend
pnpm exec playwright install chromium
pnpm test:e2e
```

Business/API tests cover dietary filtering, menu source, session isolation, supported options, server totals, confirmation gating, changed/expired quotes and idempotency, actual ADK calls, A2UI envelopes and HITL resume. Browser tests exercise desktop and mobile cart/checkout and steak customization. Verification results and limitations are recorded in `VERIFICATION.md`.

## Background jobs

`scripts/jobs.py` runs dependency installation or checks and launches an independent monitor. Status, output and timestamped monitor events are in `.local/tasks/<task>/`. The monitor checks process liveness and new error keywords every five seconds, warns on a three-minute log stall, and has a 30-minute bound. Only transient dependency-download failures get one retry; tests and live Agent requests are not automatically repeated.

`scripts/dev.py` supervises the two local servers, records health and new error log events, and restarts a server up to three times in a ten-minute window when its own output names a recognized network fault. Output from earlier sessions is ignored, and a server that stays down is reported while the other keeps serving. `--status` reads persisted state once. Windows notifications are local notifications; these scripts do **not** claim to wake a model or chat automatically. Unknown failures require inspecting the recorded logs. During implementation, failures are handled in the active development session.

Food photos are local assets. `frontend/public/images/sources.json` records source image URLs and the Unsplash license. Stock photos are illustrative; actual plating may differ. A missing image has a clearly labelled local fallback.

## Files

```text
backend/agent.py             ADK agent + official A2UI generation tool
backend/config.py            DOT / Gemini / Mock model adapter
backend/tools.py             ADK business tools
backend/store.py             SQLite carts, quotes and orders
backend/surfaces.py          composed A2UI dining workflows and mock menu fixtures
backend/recommendations.py   validated filters and party-size portion suggestions
backend/mock_model.py        explicitly scripted offline model
backend/app.py               FastAPI / AG-UI stream
backend/data/menu.json       24-dish fixtures
frontend/src/app/a2ui/       Zod definitions, React renderers and catalog
frontend/src/app/page.tsx    dining UI, AG-UI connection and Inspector
scripts/                    install / monitor / startup helpers
tests/                      backend business and protocol tests
frontend/tests/             Playwright desktop/mobile flows
```

## Official integration references

- https://a2ui.org/guides/a2ui-with-any-agent-framework/
- https://docs.copilotkit.ai/google-adk/generative-ui/a2ui/dynamic-schema
- https://docs.copilotkit.ai/google-adk/generative-ui/a2ui/fixed-schema
- https://docs.copilotkit.ai/google-adk/human-in-the-loop
- https://docs.ag-ui.com/concepts/architecture

The named `ag-ui-a2ui-integration` and CopilotKit skills were not present in the installed skill directories; implementation uses the official documentation and installed SDK source/types directly.
