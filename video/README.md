# hermes-cartographer — The Repo, Mapped

A 26-second Hyperframes piece about the plugin: repo map, symbol lookup,
references, and AST-safe rename. 1920×1080, 30 fps, H.264, 48 kHz stereo AAC.

| File | What |
| --- | --- |
| `index.html` | The video. Self-contained HTML/CSS/JS; opens in any browser and autoplays. |
| `hermes-cartographer.mp4` | A recorded render of the same file (26.6 s, 2.5 MB, with the synthesized score). |
| `audio/cues.json`, `render_audio.py` | Cue sheet and deterministic renderer for `audio/mix.wav`. |
| `mux-audio.ps1` | Stream-copies the recording and muxes the score into the MP4. |

## Play it

Open `index.html` in a browser. It autoplays, scales to any window, and never
scrolls. Click **Sound on** to start the score; browsers require that gesture
before audio can play. Click elsewhere to advance, `←`/`→` to seek, `Space` to
pause, `R` to restart. `window.__carto.seekToStartOf(n)` jumps to frame `n`
for frame-accurate capture.

`?capture=1` holds the first frame, hides the sound button, and disables the
click/keyboard shortcuts so a recorder starts from a stable state and
`window.__carto.play()` begins the take.

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

The checked-in MP4 was recorded at 1920×1080, 30 fps from the live page in
`?capture=1` mode (26.8 s raw, trimmed to 26.6 s by the mux). To re-record,
open the page with `?capture=1`, start a screen recording, call
`window.__carto.play()`, wait for the end card, and stop. Then run the mux:

```powershell
powershell -File video/mux-audio.ps1 -PreRollMs 0
```

The script stream-copies the video, encodes `audio/mix.wav` to AAC 192k, and
trims to the shorter stream. The pre-roll for the checked-in file is 0 ms: the
recorder's first encoded frame lands just after `play()`. If a future recording
starts earlier, measure the first frame where the HUD bar turns blue and pass
that offset instead.

## Audio

The score is synthesized, not sampled. `audio/cues.json` lists every hit, and
`render_audio.py` renders it deterministically with the standard library:

```powershell
python video/render_audio.py          # render and validate
python video/render_audio.py --check  # validate the existing WAV
```

`audio/mix.wav` is 48 kHz, 16-bit stereo, 26.6 s. The bed is 120 BPM: A-minor
pad, 55 Hz sub, 60 Hz pulse on the beat, hats on eighths; it ducks 9 dB under
the rename beat (17.0–21.9 s). SFX: boom at the index, ticks on the stats, map
lines, and references, whooshes into cuts 2–5, bell on the symbol hit, thud on
the stamp, blip on `applied`, chime on install, and typing clicks in frames 1
and 6. The preview plays the same WAV and resyncs it when it drifts more than
90 ms from the page clock. No voiceover, no third-party audio.

## Notes

Only external request is Google Fonts (Inter, JetBrains Mono) with local
fallbacks; everything else is inline and the audio is generated locally. The
page renders identically with the fonts blocked, at the cost of the intended
type.
