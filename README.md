# I gave an agent a browser: what broke?

The fixture, harness, raw results, transcripts, and screen clips behind episode 2.

## Finding

Four models, one local shopping task, 20 steps each.

| Agent | Result | Steps | Time | Failure |
|---|---|---:|---:|---|
| DeepSeek chat | **success** | 11 | 22.4 s | — |
| DeepSeek reasoner | **success** | 12 | 19.6 s | one bad click, recovered |
| Qwen2.5 7B | fail | 20 | 106 s | clicked the product heading, never closed the modal |
| Qwen2.5-Coder 7B | fail | 20 | 98 s | clicked “View details” behind the modal 18 times |

Gold: **Aero Mug, $18**, rating 4.4, in stock.

The local models did not fail at language. They failed at **state**: they opened a product modal,
then kept acting on the page behind it and never used the visible “Close” button.

## Fixture

`fixture/shop.html` is a self-contained shop:

- Five products with price, rating, and stock hidden behind a “View details” modal.
- A full-screen cookie consent banner that blocks the first click until accepted.
- “In stock only” and sort controls.
- One correct answer: the cheapest in-stock product rated 4.0 or higher.

No network, no bot walls, no rate limits. The same fixture runs for every agent.

## Harness

`run_browser_test.py`:

- Playwright Chromium, 1280×720, screen recording.
- A one-action-per-turn JSON protocol: `click`, `fill`, `press`, `extract`, `finish`.
- Selectors may be CSS or Playwright text selectors (`text=View Aero Mug`).
- 20 steps, temperature 0.
- DeepSeek via API; local models via Ollama.
- Records actions, observations, screenshots, and a WebM per agent.

```bash
python3 run_browser_test.py \
  --agents deepseek-chat,deepseek-reasoner,qwen2.5:7b,qwen2.5-coder:7b \
  --max-steps 20
```

## Files

- `results.json` — full trajectories, actions, observations.
- `transcript.md` — the readable table and step log.
- `clips/` — the screen segments used in the episode.
- `fixture/shop.html` — the deterministic shop.

## Caveats

- One run per agent at temperature 0; a signal, not a benchmark.
- The fixture is small and authored by us; the cookie banner is deliberately obstructive.
- The 20-step budget is tight; the API models used 11–12.
- Local and API latency are not comparable.

## Licence

MIT for the code and fixture.
