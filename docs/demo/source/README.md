# Video and audit report sources

Everything needed to rebuild the silent walkthrough (`docs/demo/demo.mp4`) and the audit report
(`docs/demo/AUDIT_REPORT.*`) from this repository alone. Paths below are relative to the repo root.

## What is here

| Path | What it is |
|---|---|
| `index.html` | Root of the video: theme (colours, type), and the timing of every slide |
| `compositions/bg.html`, `compositions/chrome.html` | Background grid, and the persistent project label, slide counter and progress bar |
| `compositions/s01-context.html` | Slide 01, the industry and four everyday problems |
| `compositions/s02-hook.html` | Slide 02, the project in one sentence |
| `compositions/explainer.html` | Slides 03-04, the white "how it works" chapter (edit its `CONFIG` block and slide B) |
| `compositions/s03-architecture.html` | Slide 05, the layered architecture diagram (boxes + the `wires` list) |
| `compositions/s04-routes.html` | Slide 06, the buffer chart and the stock-versus-service frontier read at the legacy fill rate |
| `compositions/value.html` | Slide 07, the purchase-order proposals and planner scene (data injected by `tools/inject_sheet.py`) |
| `compositions/s05-results.html`, `s06-twist.html`, `s07-end.html` | Slides 08-10, results, what didn't win, end card |
| `assets/buffer-*.png`, `assets/frontier.png` | Dark versions of `outputs/buffer_chart.png` and `outputs/frontier.png`, made by `tools/darkmap.py` |
| `assets/po_sheet.json` | Purchase-order proposals for Monday 2025-09-08, exported by `tools/export_po_sheet.py` |
| `audit/facts.yaml` | Every figure (F-xx), assumption (A-xx), slide text and check expression used by the report |
| `tools/build_audit_report.py` | Builds the slide stills, re-checks every figure against the repo outputs, writes MD, DOCX and PDF |
| `tools/export_po_sheet.py` | Re-runs the repo's own DDMRP simulation and exports one day's purchase orders as JSON |
| `tools/inject_sheet.py` | Inlines that JSON into `compositions/value.html` (renders cannot fetch files) |
| `tools/darkmap.py` | Converts the matplotlib charts into the dark panels used on slides 06 and 10 |
| `package.json`, `hyperframes.json`, `meta.json` | HyperFrames project files (CLI pinned to 0.8.156) |

Fonts (Inter, JetBrains Mono, Montserrat) are referenced by name and embedded by the HyperFrames
renderer; all three are SIL Open Font License.

## Requirements

- Node 22 and `npx` (HyperFrames 0.8.156 is fetched by `npx`), plus Chrome/Chromium for rendering.
- `ffmpeg` for compressing the video and extracting slide stills.
- LibreOffice (`soffice`) to convert the report to PDF.
- The repo's own environment (`uv sync`) for `make run` and `export_po_sheet.py`.
- For `build_audit_report.py`, `inject_sheet.py` and `darkmap.py` (any Python 3.11+, not added to the
  repo's `pyproject.toml`): `pip install pyyaml pandas python-docx pillow numpy matplotlib`.

## Rebuild the numbers, the video and the report

```bash
# 1. repo outputs (about 20 seconds)
make run

# 2. inputs for the video
python3 docs/demo/source/tools/darkmap.py outputs docs/demo/source/assets
PYTHONPATH=src .venv/bin/python docs/demo/source/tools/export_po_sheet.py docs/demo/source/assets/po_sheet.json 2025-09-08
python3 docs/demo/source/tools/inject_sheet.py docs/demo/source/assets/po_sheet.json \
  docs/demo/source/compositions/value.html \
  --rows LUB-0022,LUB-0304,LUB-0540,LUB-0079,LUB-0788,LUB-0035 \
  --animate LUB-0022,LUB-0304,LUB-0079,LUB-0035

# 3. render (86.4 s, 1920x1080, 30 fps, silent) and compress
cd docs/demo/source
npx --yes hyperframes@0.8.156 check
npx --yes hyperframes@0.8.156 render -f 30 -q looks -o renders/ddmrp-buffers-master.mp4
cd -
ffmpeg -y -i docs/demo/source/renders/ddmrp-buffers-master.mp4 -c:v libx264 -preset slow -crf 25 \
  -pix_fmt yuv420p -movflags +faststart -an docs/demo/demo.mp4

# GIFs: the end-user value slide (12 s) and the architecture data flow + critical path (7.8 s loop)
GIF='fps=12,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle'
ffmpeg -y -ss 55.6 -t 12 -i docs/demo/source/renders/ddmrp-buffers-master.mp4 -vf "$GIF" -loop 0 docs/demo/demo.gif
ffmpeg -y -ss 32.4 -t 7.8 -i docs/demo/source/renders/ddmrp-buffers-master.mp4 -vf "$GIF" -loop 0 docs/demo/architecture.gif

# 4. audit report: slide stills, automated checks, AUDIT_REPORT.md/.docx/.pdf
python3 docs/demo/source/tools/build_audit_report.py docs/demo/source/audit/facts.yaml
```

`build_audit_report.py` exits with code 1 if any figure on screen no longer matches the repo outputs.
Data and lead-time draws are seeded, so a fresh `make run` should reproduce the
same numbers; the report lists which figures and slides each assumption affects (change-impact matrix).

The `renders/` folder (about 14 MB) is not committed; step 3 recreates it.
