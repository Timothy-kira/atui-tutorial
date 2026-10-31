# Maison AI — Your Personal Dining Assistant

A local DevFest hands-on restaurant demo. The UI follows the presentation: Google Sans Flex, `#fbfbfd` background, white/gray rounded panels, Google blue actions and restrained Google color accents.

The Agent page follows the centered GPT "Now" example in the presentation: one article-like conversation column, a fixed composer, and A2UI forms, lists and order reviews embedded directly alongside the messages. There is no separate right-hand workspace or "Open dining cards" launcher. Historical responses remain in the conversation.

The local DOT preview provider still has intermittent generation/behavior failures; full live regression is not all green. See VERIFICATION.md for the current evidence and limits. A successful rendered sample does not establish reliability for every request.

## Hands-on exercise

Optimize the layout and interactions for mobile use, then improve the app and redesign the interface based on your own understanding. Use this project as a starting point for your own version.

## Start

For live generation, copy `.env.example` to `.env` and set `GOOGLE_API_KEY`. Gemini is the default. Use `--mock` only when intentionally demonstrating scripted model decisions; it still exercises the real protocol and renderer.

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
| Explicit offline mode | `MODEL_PROVIDER=mock` or launch `python scripts/dev.py --mock` |

DOT uses ADK's `LiteLlm` OpenAI-compatible adapter with the required **`api-key` header**. Thinking is disabled for this interactive demo. A2UI v0.9 is intentionally used throughout; it matches the installed CopilotKit renderer. The presentation's simplified v1.0 example is a separate teaching artifact.

`MAISON_UI_MODE=dynamic` is the default. The ADK agent chooses business tools, reads actual records, then calls `generate_a2ui`. Its model-based compositor chooses the nodes, IDs, arrangement, content and permitted actions for this request. The backend validates the graph against schemas exported from the actual React catalog; it does not select a page template. Greetings, capability questions and requests to avoid cards remain ordinary conversation.

`MAISON_UI_MODE=fixed` explicitly opts into the older fixed-schema examples. Mock mode remains visibly scripted. Dynamic mode uses an ADK `BaseTool` and a JSON-output model compositor to emit A2UI v0.9; it does not use the earlier secondary layout generator or a private SDK wrapper. Components are predefined, as A2UI requires; complete pages are composed by the Agent. See [A2UI patterns](https://docs.showcase.copilotkit.ai/google-adk/generative-ui/a2ui/index).

Mock Mode is explicitly labelled. Its scripted `BaseLlm` runs through the real ADK runtime and AG-UI adapter, and its surfaces use the real A2UI renderer. Its decisions and layouts are deterministic fixtures, **not live AI-generated UI**. No automatic fallback silently changes a live request into a mock result.

## Architecture

```text
Next.js / React + CopilotKit
  → AG-UI HttpAgent → FastAPI → ag-ui-adk → ADK Restaurant Agent
      → real business FunctionTools → menu.json / SQLite
      → business facts → generate_a2ui → model-authored graph + explanation
  ← AG-UI TOOL_CALL_RESULT / state snapshots / model-authored text
  → official A2UIProvider + A2UIRenderer + registered React catalog
  → local option/data-model changes → A2UI action in AG-UI forwardedProps
  → ADK handle_ui_action → validated business command → A2UI tool result
```

CopilotKit is self-managed against the local AG-UI endpoint. `frontend/scripts/export-catalog.mjs` exports React component schemas to `backend/data/ui-catalog.json`; rerun it after catalog changes. The frontend applies operations from actual tool-result events to the official renderer; it does not treat text containing JSON as a rendered surface. The compositor emits a JSON graph without relying on the compatible provider's complex tool-argument grammar. Validation issues feed back into at most one composition repair.

Natural-language turns use AUTO function calling. A selected UI-producing business tool invokes the model compositor in its after-tool hook and returns the actual business facts plus A2UI operations in the same result. There is no second hidden execution-audit model or keyword intent router. `generate_a2ui` remains independently callable for comparisons and corrections. Internal fact reads can use `render_ui=False`. A rendering failure is reported as `ui_error` without turning a successful cart operation into a failed mutation; retrying a display must not add the item twice. Hooks strip historical UI transport while preserving facts and never provide canned speech.

Explicit button commands use a hook to dispatch the exact validated action once. After execution the model describes its actual outcome in its own words; the same click cannot be repeated as another mutation. The frontend creates no synthetic tool messages and no longer calls a separate `/actions` mutation endpoint.

The callable `generate_a2ui` can create or update a generated surface, including an error notice, input correction or comparison table. Invalid graphs return actionable issues and `displayed:false`, allowing the Agent to repair them. Unknown components, missing/cyclic references, invented totals and invalid confirmation fields are rejected. There is no automatic fallback to a preselected page.

The restaurant catalog composes layout, dish photos/prices/facts, options, quantities and cart controls. It also registers `RecommendationFilters`, `ServingInfo`, `NutritionTotal`, `CalorieControls`, `ReservationForm`, and `ReservationStatus` for the dining workflows. Recommendation cards remain composed from individual A2UI components. The frontend `ask_user` is registered using `useHumanInTheLoop`; ADK sees it through `AGUIToolset`.

The catalog also includes `Notice`, `DataTable`, generic `Form` and `Field` primitives. The compositor can build a form from individual fields; it is not restricted to the legacy whole-form widgets. Cards accept `footerChildren` to align quantities and actions. Desktop grids have two columns; narrow screens stack into one. The composer is centered with a 780px maximum width. The earlier experimental `streaming_a2ui.py` wrapper is not imported.

## Business rules

- 24 dishes: 4 appetizers, 7 mains, 5 pasta/pizza, 4 desserts, 4 drinks; one sold-out item.
- Dietary filters and actual availability come from `backend/data/menu.json`.
- Prices and cart totals come from backend data and integer cents. The model never supplies a trusted price.
- Cart keys are per-tab session/thread UUIDs. This is a loopback workshop app, not a deployed multi-user authentication system.
- Selecting options and quantities updates local A2UI surface data; Add to cart submits their current values.
- Checkout creates an expiring quote. The Agent composes its review using the actual quote and confirmation fields. It does not submit an order.
- Confirm Order requires a matching explicit UI action, valid quote, unchanged cart revision, and an idempotency key. Chat alone cannot authorize placement.
- SQLite persists demo orders; GET `/orders/{threadId}` retrieves them. There is no payment, kitchen or delivery integration.
- Unknown actions/options and sold-out dishes are rejected. Components render React content and do not execute generated JavaScript.

## Dining workflows

Open **Agent** and select a suggested question or ask for recommendations, a reservation, calories or checkout. Business tools return actual records; generate_a2ui composes and validates their interface operations. All workflow forms and result cards use the registered A2UI catalog.

- **Recommendations:** filter 1–12 diners, vegetarian/vegan preferences, excluded declared allergens, a calorie limit per person per candidate dish, and a group price limit per candidate dish. Each card shows its real menu image, unit price and suggested portions. Per-person calories, portion totals and declared allergens appear in the conversation. Changing quantities updates the card preview; Add to table updates the authoritative cart. These are alternatives, not a combined meal plan. Allergen filters use declared recipe allergens; cross-contact information is unavailable.
- **Calories and checkout:** totals are calculated on the server as recipe kcal × selected portions. The calorie surface shows each line, total energy, and an equal split for the entered diner count. Checkout includes the energy and price totals and retains the explicit Confirm Order gate. Calories are illustrative estimates and exclude customization changes.
- **Reservations:** enter date, start/end time and 1–12 guests. Times use Singapore restaurant time (UTC+08:00). The demo inventory has seven tables with 2, 2, 4, 4, 6, 8 and 12 seats. Check availability, choose a table, and click Confirm Reservation. SQLite checks capacity and overlapping windows atomically when saving; identical confirmation retries are idempotent. These bookings are local demo records, with no external restaurant connection.

Agent tools: `recommend_dishes`, `calculate_total_calories`, `show_reservation`, `check_reservation`, and `reserve_table`, alongside the existing cart and order tools. `GET /reservations/{threadId}` retrieves this session's saved bookings.

## Inspector and workshop

Open **Developer Inspector** with the `{}` button to see captured ADK tool calls, actual AG-UI events, latest A2UI operations and server cart state. The logs are live observations, not prewritten event examples.

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
backend/actions.py           strict UI commands executed through the ADK tool
backend/interface_tool.py    model-authored A2UI graph + catalog/business validation
backend/presentation.py      optional legacy fixed-schema examples
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

## Recording versus implementation

The presentation-only HTML Showcase is a separate recording fixture, not the workshop application. Start this project for implementation work. The A2UI v0.9 messages from this application are authoritative for runnable examples; simplified v1.0-style presentation diagrams are conceptual, not copy-paste protocol payloads. Order preparation and pickup animation in the video is simulated: the application does not track a real kitchen.
