## DN-Studio · Structured Repo

This repo is a production-ready extraction of `sabarish.ipynb`:
speaker diarization (Whisper + resemblyzer) plus **MoM / BRD artifact
generation via Google Gemini**.

### Layout

- `dn_studio/`: Python package
  - `config.py`: reads `cfg/config.yaml` and exposes constants
  - `diarization_pipeline.py`: end-to-end diarization
  - `timeline_renderer.py`: HTML visualization
  - `generalised_mom_generator.py`: MoM artifacts from MoM JSON
  - `generalised_brd_generator.py`: BRD DOCX from BRD JSON
- `cfg/config.yaml`: main config (audio, models, paths)
- `prompts/`: LLM prompt JSONs used by the MoM/BRD generators
- `outputs/`: created at runtime for diarization and docs
- `main.py`: console-first CLI frontend
- `dn_studio/server.py`: Flask dashboard server

### Install

From the repo root (`ki`):

```bash
python -m venv venv
venv\Scripts\activate  # on Windows PowerShell
pip install -r requirements.txt
```

Put your audio file as `inputs/meeting_audio.mp3` or update
`audio.gdrive_url` / `paths.audio` in `cfg/config.yaml`.

### Configure LLM (Gemini)

The MoM and BRD generators use Google Gemini via `langchain-google-genai`.

1. Create a `.env` file in the repo root:

```env
GOOGLE_API_KEY=YOUR_GOOGLE_API_KEY_HERE
```

2. Make sure `.env` is **not committed** (it is already ignored in `.gitignore`).

3. When running anything that calls the LLM (dashboard or CLI helpers),
   ensure the key is loaded, for example on Windows PowerShell:

```powershell
cd C:\Users\Selvam Sabarish\Downloads\dn-studio-rqg
$env:GOOGLE_API_KEY = ((Get-Content .env | Select-String 'GOOGLE_API_KEY=').ToString().Split('=')[1].Trim())
```

The LLM runtime also reads model/temperature/max_tokens from `cfg/config.yaml`
under the `llm:` section.

### Console usage (optional helpers)

- **Diarization** (frontend = console logs):

```bash
python main.py diarize --audio inputs/meeting_audio.mp3 --out outputs/diarization
```

Artifacts land in `outputs/diarization`:
`transcript.json`, `summary.json`, `transcript.md`, `viz.html`.

- **Generate MoM artifacts** (from a MoM JSON you already have):

```bash
python main.py mom path/to/mom.json --output-dir outputs/artifacts/mom
```

- **Generate BRD DOCX** (from a BRD JSON you already have):

```bash
python main.py brd path/to/brd.json --output outputs/artifacts/brd/BRD.docx
```

### Run dashboard server locally (recommended surface)

From the repo root:

```bash
venv\Scripts\activate
python -m dn_studio.server
```

This starts Flask on port `5050` (configurable via `DN_SERVER_PORT`).
Open `http://localhost:5050` in your browser to see the DN‑Studio Project Console.

#### End‑to‑end flow in the dashboard

1. **Config tab**
   - Set *Project name*, *Experiment name*, and *Context / description*.
   - Ensure *Audio file* points to your meeting audio (see `cfg/config.yaml` paths).
   - Click **Save Config**.

2. **Diarization tab**
   - Click **Run Diarization** to run Whisper + diarization.
   - This produces `transcript.json`, `clusters.json`, `viz.html`, etc.

3. **Clusters / Transcript tabs**
   - Inspect speaker swimlanes, embeddings plots, and the full transcript
     for the selected run.

4. **MoM tab**
   - Optional: add extra MoM context in the text box.
   - Click **Generate Minutes**.
   - Backend writes `response_mom.json`, `response_mom_trace.json` and a
     compact `minutes/MoM.json` for that run.
   - The UI always renders a MoM view from `minutes/MoM.json` whenever it
     exists in the selected project/experiment run folder.

5. **BRD tab**
   - Optional: add BRD‑specific context.
   - Click **Generate BRD**.
   - Backend writes `response_brd.json` + `response_brd_trace.json`.
   - The UI always renders a BRD view from `response_brd_trace.json`
     whenever it exists in the selected project/experiment run folder.

6. **Export tab**
   - Export MoM/BRD as PDF or DOCX for the selected run.

### Exposing the console via tunneling

- **Expose the Flask dashboard publicly with localtunnel** (recommended):

  1. In one terminal, start the server and leave it running:

  ```bash
  venv\Scripts\activate
  python -m dn_studio.server   # listens on port 5050
  ```

  2. In a second terminal, start the tunnel:

  ```bash
  cd C:\Users\Selvam Sabarish\Downloads\ki
  lt --port 5050               # prints a public https://...loca.lt URL
  ```

  3. Share the printed URL (`https://...loca.lt`) as your **public DN‑Studio Project Console**.
     - If localtunnel prompts for a password, you can retrieve it from `https://loca.lt/mytunnelpassword`.

- **Alternative: SSH into the box and run the CLI directly**:

```bash
ssh user@your-host
cd /path/to/ki
python main.py diarize ...
```

### Optional: start server from a notebook

In a Jupyter / IPython notebook that runs in this repo, you can start
the same server with:

```python
import threading
from dn_studio.server import app

threading.Thread(
    target=lambda: app.run(host="0.0.0.0", port=5050, debug=False),
    daemon=True,
).start()
```

Then open `http://localhost:5050` (or tunnel it as above).


If you later add a web UI (FastAPI/Streamlit) on port 8000, you can
expose it directly with:

```bash
ngrok http 8000
```

but for this repo the product-facing surface is the CLI itself.


