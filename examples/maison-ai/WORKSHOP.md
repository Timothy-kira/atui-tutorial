# 5–8 minute hands-on walkthrough

1. **0:00–1:00 — Meet Maison AI.** Point out the mode label. Live DOT/Gemini calls a real model; Mock Mode is a scripted fallback. Open Inspector and show that the event list starts empty.
2. **1:00–2:15 — Dinner for three.** Click Dinner for three, or type “We are three people, one is vegetarian. Can you recommend a dinner for us?” Watch `get_menu` and optional `recommend_dishes` run. Show a generated surface and its component tree. Explain the server source of price/availability.
3. **2:15–3:30 — Make a choice.** Ask “I'd like a steak.” Select Medium Rare and Confirm choice. Show the tool result returning to ADK. Choose a side and quantity in the rendered UI. Those edits are local; Add to cart invokes the backend tool.
4. **3:30–4:30 — Keep the conversation going.** Ask “Add something sweet for us to share.” A new dessert surface is appended. Existing dinner surfaces and cart remain. Add a dessert; change quantity in the cart. Explain A2UI action → AG-UI → ADK tool.
5. **4:30–5:30 — Review, then confirm.** Click Checkout. The server validates and prices the cart. Confirm Order is a separate required action. Click it once and show the saved Demo Order number. No payment occurs.
6. **5:30–6:30 — Trace the stack.** Inspect the actual `TOOL_CALL_*` events, A2UI operations and cart state. ADK executes the agent, AG-UI carries interaction, A2UI describes the composed interface.
7. **6:30–8:00 — Small exercises.** Change one fixture's availability; add a dietary tag; update a catalog component's description; style the quantity selector. Restart the Python backend for fixture/tool changes. Let Next.js refresh frontend edits. Re-run a request and compare resulting component choices.

Mock Mode intentionally supports the standard menu/steak/cart/checkout path; flexible natural-language multi-item edits are a live-model exercise. Test failure cases: attempt to order the sold-out chocolate fondant, change a cart after quotation, cancel the doneness question, and confirm the same quote twice. Confirm that no duplicate order is created.
