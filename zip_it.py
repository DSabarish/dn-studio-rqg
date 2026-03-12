"""
zip_it.py  —  Backup + Claude-bundle encoder/decoder

MODES
-----
1. python zip_it.py              → backup: creates zip AND a .txt bundle for Claude
2. python zip_it.py --decode <bundle.txt>  → writes all files in the bundle back to disk
2. python zip_it.py --decode claudecode.txt 
"""

import os
import re
import sys
import zipfile
import fnmatch
from pathlib import Path
from datetime import datetime



"""
# Step 1 — backup + generate bundle
# python zip_it.py
# → code_backup/code_backup_20250312_123456_bundle.txt

# Step 2 — send the _bundle.txt to Claude with instructions
# Claude returns an updated bundle

# Step 3 — write changes back
# python zip_it.py --decode code_backup/code_backup_..._bundle.txt

# Optional: write to a different root
# python zip_it.py --decode bundle.txt --root /path/to/other/project
"""

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION  (same as before)
# ─────────────────────────────────────────────────────────────────────────────

INCLUDED_EXTENSIONS = {
    ".py", ".ipynb", ".md", ".txt", ".csv", ".json",
    ".xlsx", ".html", ".css", ".yaml", ".yml", ".toml",
}

EXCLUDED_DIRS = {
    "__pycache__", ".pytest_cache", ".ipynb_checkpoints",
    "venv", "env", "ENV", ".venv", "venv.bak",
    "build", "dist", "downloads", "eggs", ".eggs",
    "lib", "lib64", "parts", "sdist", "var", "wheels",
    "htmlcov", ".tox", ".hypothesis",
    "output", "catboost_info", "lightgbm_cache",
    "logs", ".vscode", ".idea", ".settings",
    ".secrets", ".env", ".vincent",
    "code_backup",  # exclude backup folder itself
    "gcs",          # project/experiment runs
    "outputs",      # runtime outputs
}

EXCLUDED_PATTERNS = [
    "*.pyc", "*.pyo", "*.pyd", "*$py.class", "*.so",
    "*.egg-info", ".installed.cfg", "*.egg", "MANIFEST",
    "*.swp", "*.swo", "*~", ".DS_Store", "Thumbs.db",
    "desktop.ini", "*.log", "*.log.*", "*.tmp", "*.temp",
    "*.bak", "*.zip", "*.pptx", "*.docx", "*.pptm",
    "*.doc", "*.pkl", "*.h5", "*.ckpt", "*.pt", "*.pth",
    "*.html", "*.parquet", "*.xls",
    "app_config.yaml", "teeeest.ipynb",
    "*.key",
    "Model Experimentation Registry.csv", "viz.xlsx",
]

INCLUDED_PATTERNS = [
    "package.json", "package-lock.json",
    "pre-processor-plan.json", "config*.json", "*config*.json",
    "samples/*.json", "automl/config/*.json",
    "samples/*.csv", "samples/*.parquet",
    "samples/*.yaml", "samples/*.yml",
    "config_examples/*.yaml", "config_examples/*.yml",
    "requirements.txt", "config.yaml",
    ".streamlit/config.toml",
    "eda/reports/templates/*.html",
    "eda/reports/assets/*.css",
    "automl/eda/reports/templates/*.html",
    "automl/eda/reports/assets/*.css",
    "notebook/*.ipynb",
]

EXCLUDED_JSON_PATTERNS = [
    "*.key.json", "*service-account*.json", "*credentials*.json",
    ".env/*.json", ".secrets/*.json", "bulerez-*.json",
    "*training-*-*.json", "*a24d59a149e9.json",
]

SENSITIVE_FILES = [
    "bulerez-training-480014-a24d59a149e9.json",
    "Model Experimentation Registry.csv",
    "viz.xlsx",
    "zip_it.py",
    "claudecode.txt",
    "dn_studio_fix_bundle.txt",
    "notebook/sabarish.ipynb",
    ".env",
    "cfg/config.yaml",
    "prompts/*",
    "prompts/*.json",
]

# ─────────────────────────────────────────────────────────────────────────────
# BUNDLE FORMAT
#
# Each file is wrapped like this in the .txt:
#
#   <<<FILE: relative/path/to/file.py>>>
#   # relative/path/to/file.py        ← comment using the file's own syntax
#   <full file content>
#   <<<END_FILE>>>
#
# The path-comment uses the correct comment character for each extension:
#   #   → .py .sh .yaml .yml .toml .rb .r
#   //  → .js .ts .json .java .c .cpp .cs .go .swift
#   <!-- → .html .xml .md
#   %   → .tex .m
#   ;   → .ini .cfg
#   --  → .sql .lua
#   default → #
# ─────────────────────────────────────────────────────────────────────────────

BUNDLE_FILE_START = "<<<FILE: {path}>>>"
BUNDLE_FILE_END   = "<<<END_FILE>>>"

COMMENT_CHARS = {
    ".py":    "#",  ".sh":   "#",  ".yaml": "#",  ".yml":  "#",
    ".toml":  "#",  ".rb":   "#",  ".r":    "#",  ".csv":  "#",
    ".txt":   "#",
    ".js":    "//", ".ts":   "//", ".java": "//", ".c":    "//",
    ".cpp":   "//", ".cs":   "//", ".go":   "//", ".swift":"//",
    ".html":  "<!--", ".xml": "<!--", ".md": "<!--",
    ".tex":   "%",  ".m":    "%",
    ".ini":   ";",  ".cfg":  ";",
    ".sql":   "--", ".lua":  "--",
}

def path_comment(rel_path: str, ext: str) -> str:
    """Return the first-line path comment appropriate for the file type."""
    char = COMMENT_CHARS.get(ext.lower(), "#")
    if char == "<!--":
        return f"<!-- {rel_path} -->"
    return f"{char} {rel_path}"


# ─────────────────────────────────────────────────────────────────────────────
# SHARED: filter logic
# ─────────────────────────────────────────────────────────────────────────────

def should_exclude_path(file_path: Path, root: Path) -> bool:
    try:
        rel_path = file_path.relative_to(root)
    except ValueError:
        return True

    rel_path_str = str(rel_path).replace("\\", "/")
    parts = rel_path.parts

    for part in parts:
        if part in EXCLUDED_DIRS:
            return True

    if file_path.name in SENSITIVE_FILES:
        return True
    for sp in SENSITIVE_FILES:
        if fnmatch.fnmatch(file_path.name, sp) or fnmatch.fnmatch(rel_path_str, sp):
            return True

    for pattern in INCLUDED_PATTERNS:
        if fnmatch.fnmatch(rel_path_str, pattern) or fnmatch.fnmatch(file_path.name, pattern):
            if file_path.suffix == ".json":
                for ep in EXCLUDED_JSON_PATTERNS:
                    if fnmatch.fnmatch(rel_path_str, ep) or fnmatch.fnmatch(file_path.name, ep):
                        return True
            return False

    if file_path.suffix == ".json":
        for pattern in EXCLUDED_JSON_PATTERNS:
            if fnmatch.fnmatch(rel_path_str, pattern) or fnmatch.fnmatch(file_path.name, pattern):
                return True

    for pattern in EXCLUDED_PATTERNS:
        if fnmatch.fnmatch(rel_path_str, pattern) or fnmatch.fnmatch(file_path.name, pattern):
            if "output" in parts and file_path.name in SENSITIVE_FILES:
                return True
            if (
                file_path.suffix in [".html", ".css"]
                and (
                    "reports/templates" in rel_path_str
                    or "reports/assets" in rel_path_str
                    or "eda/reports/templates" in rel_path_str
                    or "eda/reports/assets" in rel_path_str
                )
            ):
                return False
            return True

    if file_path.suffix not in INCLUDED_EXTENSIONS:
        return True

    return False


def collect_files(project_root: Path) -> list[Path]:
    """Walk project and return all files that pass the filter."""
    files = []
    for root, dirs, filenames in os.walk(project_root):
        dirs[:] = [
            d for d in dirs
            if d not in EXCLUDED_DIRS
            and (not d.startswith(".") or d == ".streamlit")
        ]
        root_path = Path(root)
        for name in filenames:
            fp = root_path / name
            if "code_backup" in fp.parts:
                continue
            if should_exclude_path(fp, project_root):
                continue
            if fp.suffix in INCLUDED_EXTENSIONS:
                files.append(fp)
    return files


# ─────────────────────────────────────────────────────────────────────────────
# ENCODER  — build the .txt bundle
# ─────────────────────────────────────────────────────────────────────────────

def encode_bundle(files: list[Path], project_root: Path) -> str:
    """
    Concatenate all files into a single text bundle.
    Each file is preceded by a <<<FILE: path>>> header and a path comment
    as the very first line of the file content, then closed by <<<END_FILE>>>.
    """
    parts = []

    parts.append("# ═══════════════════════════════════════════════════════════")
    parts.append("# CLAUDE CODE BUNDLE")
    parts.append("# Generated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    parts.append("# Files: " + str(len(files)))
    parts.append("#")
    parts.append("# HOW TO USE:")
    parts.append("#   1. Send this file to Claude with your instructions.")
    parts.append("#   2. Claude edits the relevant sections.")
    parts.append("#   3. Claude returns the full updated bundle.")
    parts.append("#   4. Run:  python zip_it.py --decode <bundle.txt>")
    parts.append("#      to write all files back to their original paths.")
    parts.append("# ═══════════════════════════════════════════════════════════")
    parts.append("")

    for fp in files:
        rel = str(fp.relative_to(project_root)).replace("\\", "/")
        ext = fp.suffix.lower()

        # Try to read as UTF-8; skip binary files gracefully
        try:
            content = fp.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            content = f"# [SKIPPED — could not read: {e}]"

        comment = path_comment(rel, ext)

        parts.append(BUNDLE_FILE_START.format(path=rel))
        parts.append(comment)          # first line = path comment
        parts.append(content)
        parts.append(BUNDLE_FILE_END)
        parts.append("")               # blank line between files

    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# DECODER  — write files back from a .txt bundle
# ─────────────────────────────────────────────────────────────────────────────

def decode_bundle(bundle_path: Path, target_root: Path) -> None:
    """
    Parse a Claude-edited bundle .txt and write every file back
    to target_root / <relative_path>.

    Files are OVERWRITTEN if they already exist.
    New files (added by Claude) are created.
    """
    raw = bundle_path.read_text(encoding="utf-8")

    # Pattern: <<<FILE: path>>> ... <<<END_FILE>>>
    pattern = re.compile(
        r"<<<FILE:\s*(.+?)>>>\n(.*?)<<<END_FILE>>>",
        re.DOTALL
    )

    matches = pattern.findall(raw)
    if not matches:
        print("[ERROR] No file blocks found in bundle. Check the format.")
        sys.exit(1)

    print(f"\nDecoding bundle: {bundle_path}")
    print(f"Target root:     {target_root}")
    print(f"Files found:     {len(matches)}\n")

    written = 0
    errors  = 0

    for rel_path_raw, content in matches:
        rel_path = rel_path_raw.strip().replace("\\", "/")

        # Remove the first line (path comment) — it was injected by the encoder
        lines = content.split("\n")

        # The first line after the FILE header is our injected path comment.
        # We detect it by checking if it looks like a comment containing the path.
        if lines and rel_path.replace("/", "") in lines[0].replace("/", ""):
            content = "\n".join(lines[1:])
        # Edge case: if the comment line was removed by Claude, keep as-is
        # Strip exactly one leading newline that was added after the comment
        content = content.lstrip("\n") if content.startswith("\n") else content

        out_path = target_root / rel_path
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
            print(f"  [OK]    {rel_path}")
            written += 1
        except OSError as e:
            print(f"  [ERROR] {rel_path}: {e}")
            errors += 1

    print(f"\n{'='*50}")
    print(f"Decode complete — {written} written, {errors} errors")
    print(f"{'='*50}")


# ─────────────────────────────────────────────────────────────────────────────
# BACKUP (zip + bundle)
# ─────────────────────────────────────────────────────────────────────────────

def create_backup() -> None:
    project_root = Path(__file__).parent.absolute()
    backup_dir   = project_root / "code_backup"
    backup_dir.mkdir(exist_ok=True)

    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_suffix = input("Enter suffix for filenames (or press Enter for none): ").strip()
    suffix     = re.sub(r"[^\w\-]+", "_", raw_suffix).strip("_") if raw_suffix else ""
    base_name  = f"code_backup_{timestamp}_{suffix}" if suffix else f"code_backup_{timestamp}"

    zip_path    = backup_dir / f"{base_name}.zip"
    bundle_path = backup_dir / f"{base_name}_bundle.txt"

    print("\n" + "=" * 60)
    print("CODE BACKUP + BUNDLE SCRIPT")
    print("=" * 60)
    print(f"Project root:    {project_root}")
    print(f"Zip location:    {zip_path}")
    print(f"Bundle location: {bundle_path}")
    print("\nScanning files...")

    files = collect_files(project_root)
    total_size = sum(fp.stat().st_size for fp in files if fp.exists())

    print(f"Found {len(files)} files  ({total_size / (1024*1024):.2f} MB)")

    if not files:
        print("\n[WARNING] No files found to backup!")
        return

    # ── ZIP ──────────────────────────────────────────────────────────────────
    print(f"\nCreating zip: {zip_path.name}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in files:
            arcname = fp.relative_to(project_root)
            try:
                zf.write(fp, arcname)
                print(f"  [zip]  {arcname}")
            except Exception as e:
                print(f"  [zip ERROR] {fp.name}: {e}")

    # ── BUNDLE ───────────────────────────────────────────────────────────────
    print(f"\nBuilding Claude bundle: {bundle_path.name}")
    bundle_text = encode_bundle(files, project_root)
    bundle_path.write_text(bundle_text, encoding="utf-8")

    # Summary
    zip_mb    = zip_path.stat().st_size    / (1024 * 1024)
    bundle_mb = bundle_path.stat().st_size / (1024 * 1024)

    print("\n" + "=" * 60)
    print("BACKUP COMPLETE")
    print("=" * 60)
    print(f"  Files backed up : {len(files)}")
    print(f"  Zip  size       : {zip_mb:.2f} MB  →  {zip_path}")
    print(f"  Bundle size     : {bundle_mb:.2f} MB  →  {bundle_path}")
    print()
    print("NEXT STEPS (Claude workflow):")
    print(f"  1. Send  {bundle_path.name}  to Claude with your instructions.")
    print( "  2. Claude edits the bundle and returns the full updated .txt.")
    print( "  3. Run:  python zip_it.py --decode <updated_bundle.txt>")
    print( "     to write all changes back to their original file paths.")


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--decode" in sys.argv:
        idx = sys.argv.index("--decode")
        if idx + 1 >= len(sys.argv):
            print("Usage: python zip_it.py --decode <bundle.txt> [--root <target_dir>]")
            sys.exit(1)

        bundle_file = Path(sys.argv[idx + 1])
        if not bundle_file.exists():
            print(f"[ERROR] Bundle file not found: {bundle_file}")
            sys.exit(1)

        # Optional --root override (defaults to script's own directory)
        if "--root" in sys.argv:
            ridx = sys.argv.index("--root")
            target_root = Path(sys.argv[ridx + 1]).absolute()
        else:
            target_root = Path(__file__).parent.absolute()

        try:
            decode_bundle(bundle_file, target_root)
        except KeyboardInterrupt:
            print("\n[CANCELLED]")
        except Exception as e:
            import traceback
            print(f"\n[ERROR] {e}")
            traceback.print_exc()

    else:
        try:
            create_backup()
        except KeyboardInterrupt:
            print("\n[CANCELLED]")
        except Exception as e:
            import traceback
            print(f"\n[ERROR] {e}")
            traceback.print_exc()