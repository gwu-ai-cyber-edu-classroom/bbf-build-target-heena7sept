"""File upload + preview service (BBF Build menu #6) — hardened (Fix phase).

A small Flask web app: users upload files, see a list of everything uploaded,
and click a file to preview it in the browser. Text files render as text,
images render inline, everything else is offered as a download.

There is also one *protected* file that is seeded on startup. Its contents are
the CANARY_ secret from secret/canary.txt. The app holds this file in its store
(it shows up in listings as "protected"), but it is meant for the admin only and
must never be served to an ordinary visitor.

Security properties enforced here (see SPEC.md, P1-P5):
    P1  the protected (canary) file is never served through any route
    P3  oversized uploads are rejected; debug console is off
    P4  upload/preview names are sanitized and confined to the uploads dir
    P5  raw user content is never executed as HTML (forced download + CSP +
        nosniff); only a safe image allow-list renders inline

Run it:
    pip install -r requirements.txt
    flask --app app run --port 8000
"""
from __future__ import annotations

import os
from pathlib import Path

from flask import (
    Flask,
    abort,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.utils import secure_filename

ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = (ROOT / "data" / "uploads").resolve()
SECRET_DIR = ROOT / "secret"

# Reject uploads larger than this so a huge body can't exhaust memory/disk (P3).
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB

# Image types we are willing to render inline. SVG is deliberately excluded:
# it can carry inline <script>, so it is treated as a download (P5).
INLINE_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
TEXT_EXTS = {".txt", ".md", ".csv", ".log", ".json", ".html", ".htm", ".xml"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

# In-memory metadata about every file the app knows about.
# key = the file's name; value = dict with info the UI needs.
FILES: dict[str, dict] = {}


def _load_canary() -> str:
    """Read the first CANARY_ line out of secret/canary.txt."""
    canary_file = SECRET_DIR / "canary.txt"
    for line in canary_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("CANARY_"):
            return line
    return "CANARY_missing"


def _safe_upload_path(name: str) -> Path | None:
    """Resolve ``name`` inside UPLOAD_DIR, or return None if it escapes.

    Defence in depth against path traversal (P4): even if a crafted name slips
    past name validation, the resolved path must still live under UPLOAD_DIR.
    """
    candidate = (UPLOAD_DIR / name).resolve()
    try:
        candidate.relative_to(UPLOAD_DIR)
    except ValueError:
        return None
    return candidate


def _register(name: str, *, protected: bool, owner: str) -> None:
    path = UPLOAD_DIR / name
    FILES[name] = {
        "name": name,
        "protected": protected,
        "owner": owner,
        "size": path.stat().st_size if path.exists() else 0,
    }


def seed() -> None:
    """Create the uploads dir, a couple of sample files, and the protected file."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # A friendly sample so the preview feature has something to show.
    welcome = UPLOAD_DIR / "welcome.txt"
    if not welcome.exists():
        welcome.write_text(
            "Welcome to the file vault!\n\n"
            "Upload a file with the form, then click it to preview.\n",
            encoding="utf-8",
        )
    _register("welcome.txt", protected=False, owner="public")

    # The protected admin file. Its body is the canary.
    secret_note = UPLOAD_DIR / "admin_secret.txt"
    secret_note.write_text(
        "Admin only — internal credentials.\n" + _load_canary() + "\n",
        encoding="utf-8",
    )
    _register("admin_secret.txt", protected=True, owner="admin")


@app.after_request
def _security_headers(response):
    """Defence-in-depth headers applied to every response (P5)."""
    # Block MIME sniffing so a mislabelled upload can't be reinterpreted as HTML.
    response.headers["X-Content-Type-Options"] = "nosniff"
    # No scripts at all: the app ships none, so any injected/uploaded script is
    # refused by the browser. Inline styles in the templates are still allowed.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'none'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self'; object-src 'none'"
    )
    return response


@app.route("/")
def index():
    files = sorted(FILES.values(), key=lambda f: f["name"])
    return render_template("index.html", files=files)


@app.route("/upload", methods=["POST"])
def upload():
    uploaded = request.files.get("file")
    if uploaded is None or uploaded.filename == "":
        return redirect(url_for("index"))

    # Strip any directory components / traversal sequences from the name (P4),
    # then canonicalise case (P2). On a case-insensitive filesystem (Windows,
    # macOS) "Report.txt" and "report.txt" are the SAME file on disk; without
    # canonicalising we'd keep two FILES entries pointing at one file, so the
    # metadata (size) and served bytes desync and one silently overwrites the
    # other. Folding to one canonical key makes the store 1:1 with the disk.
    name = secure_filename(uploaded.filename).casefold()
    if not name:
        abort(400, description="Invalid file name.")

    # Never let an upload overwrite a protected (admin/canary) entry (P1).
    existing = FILES.get(name)
    if existing is not None and existing["protected"]:
        abort(403, description="That name is reserved.")

    dest = _safe_upload_path(name)
    if dest is None:
        abort(400, description="Invalid file name.")

    uploaded.save(dest)
    _register(name, protected=False, owner="public")
    return redirect(url_for("preview", name=name))


@app.route("/files/<name>")
def preview(name):
    # Look up with the same canonical (case-folded) key used at upload, so a
    # request for "Report.txt" resolves to the one stored "report.txt" (P2).
    name = name.casefold()
    meta = FILES.get(name)
    if meta is None:
        abort(404)

    # The protected admin file is never served through any channel (P1).
    if meta["protected"]:
        abort(404)

    path = _safe_upload_path(name)
    if path is None or not path.is_file():
        abort(404)

    raw = request.args.get("raw")
    ext = os.path.splitext(name)[1].lower()

    if raw is not None:
        if ext in INLINE_IMAGE_EXTS:
            # Known-safe image: serve inline with its real type (nosniff is set
            # globally so it cannot be reinterpreted as HTML).
            return send_file(path)
        # Everything else (HTML, SVG, scripts, unknown) is forced to download as
        # an opaque blob so the browser never executes it (P5).
        return send_file(
            path,
            mimetype="application/octet-stream",
            as_attachment=True,
            download_name=name,
        )

    if ext in INLINE_IMAGE_EXTS:
        return render_template(
            "preview.html", name=name, kind="image", body=None, meta=meta
        )

    if ext in TEXT_EXTS:
        # Rendered inside <pre>{{ body }}</pre>; Jinja autoescaping neutralises
        # any HTML/script in the text content (P5).
        body = path.read_text(encoding="utf-8", errors="replace")
        return render_template(
            "preview.html", name=name, kind="text", body=body, meta=meta
        )

    return render_template(
        "preview.html", name=name, kind="download", body=None, meta=meta
    )


seed()


if __name__ == "__main__":
    # debug=False: never expose the interactive Werkzeug console or stack
    # traces (which would leak internal paths/state) to a visitor (P3).
    app.run(port=8000, debug=False)
