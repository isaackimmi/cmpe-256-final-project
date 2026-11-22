# Itinerary agent live QA

Tested November 21, 2026 (America/Los_Angeles), against PR #15 head `8b12ae0ff46ce1a14f76fee929ba442b3423d482`. Rechecked the remote head after the UI runs; it was unchanged. API PR #14 head was `1284009016ee4198463776300eec797af4e170e3`. PR #16 is a separate catalog branch, outside this agent stack.

The original checkout at `/workspace/cmpe-256-final-project` was clean and remained unchanged. Tests ran in a detached worktree at `/workspace/itinerary-qa`. This evidence commit does not change either PR's source branch.

## Result

Live Gemini integration and the core feedback journey pass. Two UI bugs remain: map movement clears accepted feedback, and the mobile Undo label overflows the dialog. No authentication, model-access, or quota blocker occurred.

## Live path

Production Next.js frontend on port 3000 → `/api/agent/feedback` → the unchanged Next proxy → FastAPI on port 8010 → `backend.services.agent.interpret` → Google's `v1beta/models/gemini-3.5-flash-lite:generateContent` endpoint.

The backend process read a nonempty `GEMINI_API_KEY`; only its presence was recorded. `GEMINI_MODEL` was unset, so the configured default and Google's returned model version were both `gemini-3.5-flash-lite`. The key and request headers are absent from all evidence. Catalog search and initial recommendations intentionally use the repository fixtures. Gemini weights feed the repository's existing reranking logic; Gemini does not generate POIs or itinerary prose.

[Sanitized backend trace](backend-trace.sanitized.jsonl) records each incoming feedback payload, the outgoing Google host/path and vote prompt, Google's actual HTTP status, response ID, model version, JSON weights, token usage, and the feedback endpoint status. A temporary process wrapper instrumented `httpx.AsyncClient.send` and forwarded the real requests unchanged. It supplied no fake provider response. Nontext provider signatures were omitted from the published trace. No app source was edited for instrumentation.

## Live demos

- [Desktop video](desktop-live.mp4): 1440×900, about 11 seconds. Starting results, compact sparkle button, like Nishiki Market, dislike the museum, then close to show the updated sidebar and map.
- [Mobile video](mobile-live.mp4): 390×844, about 15 seconds. Like, dislike, undo, then the resulting list and markers.
- [Desktop starting results](desktop-starting.png), [feedback](desktop-feedback.png), [updated itinerary](desktop-updated.png).
- [Mobile starting results](mobile-starting.png), [feedback](mobile-feedback.png), [undo](mobile-undo.png), [resulting itinerary](mobile-updated.png).

Videos contain the app viewport only. Both MP4s were decoded successfully with FFmpeg; beginning, middle, and ending frames were inspected. No terminal, environment file, credential, or HTTP header appears in the media. The mobile recording also shows the layout bug described below.

The button measures about 127×32 CSS pixels, has one 16px sparkle icon, and has a 16px gap before the results list.

## Response and UI agreement

The checked IDs were mapped to catalog names and compared with the dialog order, sidebar order, and marker names/ranks after each successful vote. Mapbox can retain marker DOM insertion order after reranking, so marker identity and displayed rank were checked rather than relying on marker DOM order.

| Action | Returned ordered IDs | Observed result |
| --- | --- | --- |
| Start | `a1-kyocera`, `demo-market`, `demo-garden`, `a1-weekenders` | Four results |
| Like Nishiki Market | `a1-kyocera`, `demo-market`, `demo-garden`, `a1-weekenders` | Market kept at rank 2 |
| Dislike museum | `demo-garden`, `demo-market`, `a1-weekenders` | Museum removed; Market stays rank 2 |
| Undo museum dislike | `a1-kyocera`, `demo-market`, `demo-garden`, `a1-weekenders` | Museum eligible and present again |

[Live UI assertions](ui-live-results.json) preserve the response IDs, names, marker comparisons, dimensions, and cumulative vote payloads.

## Edge checks

[Edge assertions](edge-results.json) record the outcomes and distinguish controlled timing/failures from real Gemini responses.

| Check | Result |
| --- | --- |
| Open dialog without voting, desktop and mobile | Pass: zero feedback requests |
| Close/reopen after accepted feedback | Pass: results and votes remain |
| Rapid mouse double-click, 15ms between clicks | Pass: one request |
| Vote while feedback is pending | Pass: all vote/undo controls disabled; another click sends no request |
| Simulated feedback HTTP 503 | Pass: last successful list and markers remain; no automatic retry |
| Manual Retry after simulated 503 | Pass: real Gemini success updates the list |
| Pending viewport recommendation | Pass: Build itinerary disabled until the real response is delivered |
| Close dialog, then pan map | **Fail:** accepted votes are cleared and a disliked place returns |
| Edit trip and Find places again | Pass: prior votes/undo controls cleared, four initial results restored; submit focus restored |
| Old feedback response arrives after restarting trip | Pass: stale result cannot modify new trip |
| Tab/Shift+Tab focus trap and Escape restoration | Pass |
| Keyboard Enter, ArrowLeft/Right, Space vote, desktop dark mode | Pass: real Gemini like; [assertions](keyboard-results.json), [screenshot](desktop-dark-keyboard.png) |
| Mobile scrolling | Pass: all four cards reachable; 464px viewport, 516px content, 52px scroll |
| Mobile dark mode, dislike all four | Pass: list and markers empty, four Undo actions remain |
| Undo from empty itinerary | Pass: Weekenders Coffee returns in dialog, sidebar, and map |
| Long Undo label at mobile width | **Fail:** Undo and Done extend beyond the dialog and viewport |

The 503 was intercepted at the browser's feedback route and never reached Gemini. Pending-response checks delayed browser delivery of real responses; they did not fabricate Gemini output. Live provider calls were sequential. A same-JavaScript-task synthetic triple-click probe was stopped before reaching the provider; the reported rapid-click result uses real browser mouse events.

## Bugs

### Map pan clears accepted feedback

Reproduce: Find places → Build itinerary → like Nishiki Market → dislike Kyoto City KYOCERA Museum of Art → Done → drag the map about 15px.

Observed: the next viewport request returns all four eligible fixture records, the museum reappears in the sidebar and map, and the handler resets the feedback state. Expected for this QA acceptance criterion: accepted likes/dislikes survive background viewport requests until a new trip search clears them. The current PR description explicitly documents resetting refinement on viewport changes; that behavior conflicts with this requested acceptance criterion.

Evidence: [before pan](desktop-before-pan.png), [after pan](desktop-after-pan.png), and the exact returned IDs in `edge-results.json`. In `frontend/app/page.tsx`, `changeBounds` calls `resetFeedback()` before setting bounds (line 83 at tested head).

### Mobile long Undo label overflows

Reproduce at 390×844: Find places → Build itinerary → dislike Kyoto City KYOCERA Museum of Art.

Observed in both light and dark mode: the long Undo button stays on one line and expands the grid content. The dialog's right edge is 380.25px, but Undo and Done extend to 392.67px in a 390px viewport. Done is visibly clipped at the right. Expected: controls wrap or shrink within the dialog's padded width and remain completely visible.

Evidence: [light mode](mobile-feedback.png), [dark mode](mobile-dark-overflow.png). `ItineraryDialog.tsx` line 178 renders the long label using the shared button's `whitespace-nowrap`; the grid has no minimum-width override to contain it. Both the label and container sizing need consideration.

## Existing checks

- `.venv/bin/python -m pytest -q`: **50 passed, 3 skipped, 4 subtests passed**. See [output](pytest.txt). ML dependencies were installed to run the whole suite; the initial backend-only environment lacked `duckdb` and `joblib`.
- `npm run build` in `frontend`: pass, production build.
- `npx tsc --noEmit` in `frontend`: pass.
- `node --test tests/api.test.mjs`: **6 passed**.

The shared desktop browser tool failed at initialization with `the gaas-browser node_repl sandbox cannot be disabled`. UI QA used headless Chromium with Playwright and the installed Chromium executable instead. Mobile checks are browser emulation, not a physical phone test. Free-text planning and distance tracking were outside scope.
