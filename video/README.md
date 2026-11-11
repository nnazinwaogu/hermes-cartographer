# hermes-cartographer — The Repo, Mapped

A 26-second Hyperframes piece about the plugin: repo map, symbol lookup,
references, and AST-safe rename. 1920×1080, 30 fps, H.264, no audio.

| File | What |
| --- | --- |
| `index.html` | The video. Self-contained HTML/CSS/JS; opens in any browser and autoplays. |
| `hermes-cartographer.mp4` | A recorded render of the same file (26.3 s, 1.7 MB). |

## Play it

Open `index.html` in a browser. It autoplays, scales to any window, and never
scrolls. Click to advance, `←`/`→` to seek, `Space` to pause, `R` to restart.
`window.__carto.seekToStartOf(n)` jumps to frame `n` for frame-accurate capture.

## Beat map

| # | In | Out | Scene | Real material |
| --- | --- | --- | --- | --- |
| 1 | 0.0 | 4.0 | Index | Typed `hermes carto index ./repo`; 378 files · 9,219 symbols · 138,317 refs · 10,456 ms |
| 2 | 4.0 | 9.0 | Turn-one context | `pre_llm_call` map, `registry.py (1219)`, `ToolRegistry.dispatch(...)`, 3,814 / 4,000 chars |
| 3 | 9.0 | 13.0 | Find, don't grep | `symbol_find("dispatch")` → `registry.py:1069` with the real signature |
| 4 | 13.0 | 17.0 | References | `symbol_refs("dispatch")`, 16 AST-precise call sites, byte-exact columns |
| 5 | 17.0 | 22.0 | Rename | `symbol_rename("run", "execute")` dry-run diff, parsed before write, applied |
| 6 | 22.0 | 26.0 | Close | `hermes plugins install hermes-cartographer`, wordmark, tagline |

The numbers and code strings come from a real index and a real run; the diff is
the real fixture signature. No invented metrics, no stock imagery, no logos.

## Design direction

Direction studied from real sites in Inspo (`feature-stack`; exemplars
`algolia-com`, `devin-ai--enterprise`, `gitkraken-com--download`,
`astro-build--blog`, `azure-microsoft-com`):

- canvas `#0a0a0a`, alt `#181818`, surface `#242424`
- text `#ffffff`, muted `#b3afb6`, one accent `#4787f5`
- Inter for display/body (4–4.5× jump, tight tracking); JetBrains Mono for code
- faint dot grid as the only texture; borderless columns; 80–160 px seams
- all-caps micro-labels at 0.18em tracking; the blinking `>_` cursor as motif
- hard cuts at frame boundaries; 200–300 ms line-print reveals;
  `cubic-bezier(.16,1,.3,1)`; no bounce, no parallax

## Rendering

`index.html` carries the skill's frame contract: six `<section class="frame">`
blocks at 1920×1080, one `<!-- frame:N duration:XXXX transition:fade -->`
marker each, and a `<!-- HYPERFRAMES_META: … -->` JSON block with the timeline,
so a Remotion/Hyperframes script can consume it without reading the JS.

The checked-in MP4 was recorded at 1920×1080, 30 fps from the live page
(26.3 s incl. pre-roll). To re-record, open the page in a 1920×1080 browser,
start a screen recording, `R` to restart, and stop after the end card.

## Notes

Only external request is Google Fonts (Inter, JetBrains Mono) with local
fallbacks; everything else is inline. The page renders identically with the
fonts blocked, at the cost of the intended type.
