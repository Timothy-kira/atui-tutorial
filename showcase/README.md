# 教学项目本地入口

`index.html` 现在跳转到 `launch.html`，引导启动 `../examples/maison-ai` 完整应用，不再加载本目录内的脚本化前端演示。实际应用位于 http://127.0.0.1:3008。

本目录其他图片、JS 和 CSS 是历史录制素材。以下记录仅说明这些素材原来的用途，不代表 ADK、AG-UI 或 A2UI 的实现。原视频工程的录制素材没有改动。

## 历史录制素材说明

Open `index.html` directly, or play the parent `video/index.html` presentation.
No development server, backend, model credentials or package installation is needed.

This is an independent frontend for recording the Showcase section. Menu records,
images, conversation text, skeletons, recommendation filters and order interactions
are local fixtures. No actual reservation, order or model request is submitted.

- `menu-data.js`: frozen snapshot of the restaurant menu.
- `images/`: independent copies of menu images.
- `showcase.js`: deterministic interactions and the presentation bridge.
- `showcase.css`: styles and transitions.

The parent presentation sends `prepare`, `explore`, `locate-agent`, `pointer`,
`recommend`, and `stop` through `devfest-maison-presentation`. For later scripted
scenes it can send `prompt` with a `text` property. This keeps scene timing separate
from the live application and permits controlled mock animations.

## Three scripted Agent chapters

Explore scrolls from top to bottom using the narration's playback progress
(approximately 14.2 seconds), rather than the standalone 70px/s fallback.
The scroll animation runs inside the iframe on its own animation frames. Parent
audio clock snapshots calibrate it every 120ms; missing individual messages do
not stop the menu scroll. A complete local duration remains available as fallback.
Only after audio completion and the iframe's bottom-of-page acknowledgement does
the parent automatically enter Recommend and start its animation and narration.
Recommend, Explain and Order each have their own local narration file. Their
audio starts after the chapter title change, stops on exit, and resets on reentry.
Their key actions use narration-clock cues rather than accumulated fixed delays.
Recommendation paragraph breaks are near 8.27s and 17.59s, the detail explanation
starts near 10.36s, and the pickup progress paragraph starts near 9.89s. Quantity
changes remain limited to adding two chicken portions and removing the lemonade.

Advance the presentation with Right / Page Down / Space. Each chapter plays its
own animation and holds the final frame until the next manual advance. Returning
to a chapter resets it to a fixed starting state.

- Recommend: choose the budget prompt, fill preferences, update, and add two
  portions of chicken from the three results.
- Explain: type an ingredient question, show nutrition and allergen details,
  collapse the panel into a conversation card, and reopen it.
- Order: review the cart, keep the two chicken portions and remove only the lemonade,
  show the updated price and calories, explicitly confirm the mock order, then
  show the numbered Confirmed / Preparing / Ready for pickup steps and pickup number M024. The status card contains only these steps and the collection number.

The iframe supports `play-flow` with `flow` set to `recommend`, `explain`, or
`order`, and emits `flow-started`, `flow-complete`, or `flow-error`. `stop` aborts
the timeline, cursor movement and pending mock content. No model request is made.

Playback also starts directly from the URL fragment, such as
`#chapter=recommend&run=1`. Explore uses `#chapter=explore&run=1`.
This is the presentation's primary trigger and works independently of readiness
messages between local file frames. Recommend includes its own animated Agent-tab
click before opening the question and filters.

Forward chapters preserve a matching open panel. Identical card content is reused
without a skeleton or reload animation. Chat only scrolls to a reply's first two
lines when they are outside the visible area; it does not follow the streaming tail.

This Showcase models counter pickup ordering. Buttons, cart review and assistant replies use pickup terminology; there is no table-service or delivery step.
