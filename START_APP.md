# START_APP.md — how to run and probe this app

> **Build team:** fill in every `<...>` below once your app runs. Other teams use this file to
> start your app and probe it during Break. Keep it accurate — a break is filed against the app a
> breaker can actually start from these instructions.

## What this app is

- **App:** File upload + preview — a "file vault" where you upload files and click them to preview (menu #6)
- **Stack:** Python + Flask

## Start it

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run it
flask --app app run --port 8000
```

- **Base URL:** http://localhost:8000
- **Stop it:** Ctrl-C in the terminal running it.

## How to interact with it

- **Main endpoints / pages:**
  - `GET /` — homepage: upload form + list of all files — open http://localhost:8000/ in a browser
  - `POST /upload` — upload a file (multipart form field `file`); redirects to its preview
  - `GET /files/<name>` — preview a file (text inline, images inline, else a download link)
  - `GET /files/<name>?raw=1` — serve the raw file bytes
- **Accounts / credentials for legitimate use** (if the app has login): none
- **A benign request that should succeed:**

  ```bash
  curl http://localhost:8000/files/welcome.txt
  ```

  Or upload a file and follow the redirect to its preview:

  ```bash
  echo "hello" > note.txt
  curl -L -F "file=@note.txt" http://localhost:8000/upload
  ```

## For breakers

Attack this **running app over HTTP** — do **not** read this repo's source or `secret/` to find a
break. See [AGENTS_BREAK.md](AGENTS_BREAK.md) for the rules and your AI agent's instructions, and
[SPEC.md](SPEC.md) for the five properties (P1–P5) you are probing for.
