# spikee/viewer/blueprints/generate.py
"""Generate Blueprint — dataset generation form and seed/dataset browsing."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    abort,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
import markdown as md_lib

from spikee.utilities.files import read_jsonl_file
from spikee.utilities.modules import (
    collect_datasets,
    collect_modules,
    collect_seeds,
    get_description_from_module,
    get_options_from_module,
    load_module_from_path,
)
from spikee.viewer.blueprints._shared import module_tags as _module_tags
from spikee.viewer.blueprints import _cache as _module_cache
from spikee.viewer.blueprints._forms import FormValidationError, GenerateForm
from spikee.generator import resolve_seed_folder
from spikee.viewer.job_queue import job_queue, spawn_job

generate_bp = Blueprint("generate", __name__)


# ── Constants ─────────────────────────────────────────────────────────────────

_DATASET_PAGE = 100  # rows shown per dataset detail page

# Files recognised inside a seed folder, in display order.
# Maps filename → (type_key, badge_classes, label)
_SEED_FILES = {
    "jailbreaks.jsonl": ("jailbreaks", "bg-danger", "Jailbreaks"),
    "instructions.jsonl": ("instructions", "bg-warning text-dark", "Instructions"),
    "standalone_user_inputs.jsonl": ("standalone", "bg-info text-dark", "Standalone"),
    "standalone_attacks.jsonl": ("standalone", "bg-info text-dark", "Standalone"),
    "base_user_inputs.jsonl": ("documents", "bg-primary", "Documents"),
    "base_documents.jsonl": ("documents", "bg-primary", "Documents"),
    "adv_prefixes.jsonl": ("adv_fixes", "bg-secondary", "Adv Prefixes"),
    "adv_suffixes.jsonl": ("adv_fixes", "bg-secondary", "Adv Suffixes"),
    "system_messages.toml": ("system_messages", "bg-secondary", "System Messages"),
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _collect_seeds_with_meta() -> list[dict]:
    """Return seed names from CWD/datasets/ as list of dicts."""
    return [{"name": s, "description": ""} for s in collect_seeds()]


def _collect_datasets_with_meta() -> list[dict]:
    """Return dataset filenames from CWD/datasets/ with entry counts."""
    datasets_dir = Path(os.getcwd()) / "datasets"
    result = []
    for name in collect_datasets():
        path = datasets_dir / name
        try:
            with open(path, encoding="utf-8") as _f:
                count = sum(1 for _ in _f)
        except OSError:
            count = None
        result.append({"name": name, "entry_count": count})
    return result


def _collect_plugins() -> dict:
    """Return plugins as {local: [{name, tags, description, options, llm_required}], builtin: [...]}."""
    _all, local_names, builtin_names = collect_modules("plugins")
    exclude = {"Single-Turn"}

    def _entry(name: str) -> dict:
        tags = [t for t in _module_tags(name, "plugins") if t["label"] not in exclude]
        description = ""
        options: list[str] = []
        llm_required = False
        try:
            mod = load_module_from_path(name, "plugins")
            desc = get_description_from_module(mod, "plugins")
            if desc and isinstance(desc, tuple) and len(desc) >= 2:
                description = str(desc[1]) if desc[1] else ""
            opts = get_options_from_module(mod, "plugins")
            if opts and isinstance(opts, tuple) and len(opts) >= 2:
                option_list, llm_req = opts
                options = list(option_list) if option_list else []
                llm_required = bool(llm_req)
        except Exception:
            pass
        return {
            "name": name,
            "tags": tags,
            "description": description,
            "options": options,
            "llm_required": llm_required,
        }

    return {
        "local": [_entry(n) for n in sorted(local_names)],
        "builtin": [_entry(n) for n in sorted(builtin_names)],
    }


def _collect_plugins_detail() -> list[dict]:
    """Return a rich list of plugin metadata for the plugins browser page.

    Each entry is a dict with:
        name        — module name
        source      — "local" or "builtin"
        tags        — [{label, colour}] (Single-Turn excluded)
        description — plain-text description string, or "" on failure
        options     — list of option strings advertised by the module, or []
        llm_required — bool; True if any option requires an LLM call
    """
    _all, local_names, builtin_names = collect_modules("plugins")
    local_set = set(local_names)
    exclude_tags = {"Single-Turn"}

    plugins = []
    for name in sorted(_all):
        tags = [
            t for t in _module_tags(name, "plugins") if t["label"] not in exclude_tags
        ]
        source = "local" if name in local_set else "builtin"

        description = ""
        options: list[str] = []
        llm_required = False
        try:
            mod = load_module_from_path(name, "plugins")
            desc = get_description_from_module(mod, "plugins")
            if desc and isinstance(desc, tuple) and len(desc) >= 2:
                description = str(desc[1]) if desc[1] else ""
            opts = get_options_from_module(mod, "plugins")
            if opts and isinstance(opts, tuple) and len(opts) >= 2:
                option_list, llm_req = opts
                options = list(option_list) if option_list else []
                llm_required = bool(llm_req)
        except Exception:
            pass

        plugins.append(
            {
                "name": name,
                "source": source,
                "tags": tags,
                "description": description,
                "options": options,
                "llm_required": llm_required,
            }
        )

    return plugins


def _normalize_row(row: dict, line_no: int = 0) -> dict:
    """Normalise a raw JSONL row to a consistent preview dict."""
    text = (
        row.get("text")
        or row.get("content")
        or row.get("document")
        or row.get("instruction")
        or row.get("suffix")
        or row.get("prefix")
        or ""
    )
    if isinstance(text, (dict, list)):
        text = str(text)
    return {
        "id": row.get("id", "—"),
        "type": row.get("jailbreak_type") or row.get("instruction_type") or "",
        "lang": row.get("lang", ""),
        "text": str(text)[:300],
        "line_no": line_no,
    }


def _load_seed_detail(seed_name: str) -> dict | None:
    """Read a seed folder from disk and return structured file info."""
    # Prevent path traversal: resolve and verify the path stays inside datasets/
    datasets_dir = (Path(os.getcwd()) / "datasets").resolve()
    seed_path = (datasets_dir / seed_name).resolve()
    if not seed_path.is_relative_to(datasets_dir):
        return None

    try:
        # collect_seeds() returns bare names; resolve_seed_folder expects "datasets/<name>"
        folder = Path(str(resolve_seed_folder(f"datasets/{seed_name}")))
    except Exception:
        return None

    files = []
    for fname, (ftype, fbadge, flabel) in _SEED_FILES.items():
        fpath = folder / fname
        if not fpath.is_file():
            continue

        if fname.endswith(".jsonl"):
            try:
                rows = read_jsonl_file(str(fpath))
            except Exception:
                rows = []
            entries = len(rows)
            preview = [_normalize_row(r, i) for i, r in enumerate(rows)]
        else:
            # .toml — parse with tomllib/tomli to extract system_message entries
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib  # type: ignore
            try:
                data = tomllib.loads(fpath.read_text(encoding="utf-8"))
                configs = data.get("configurations", [])
                entries = len(configs)
                preview = [
                    {
                        "id": i + 1,
                        "type": "",
                        "lang": "",
                        "line_no": i,
                        "text": str(cfg.get("system_message", ""))[:300].replace(
                            "\n", " "
                        ),
                    }
                    for i, cfg in enumerate(configs)
                ]
            except Exception:
                entries = "\u2014"
                preview = []

        # Detect which columns actually contain data (in display order)
        _col_order = ["id", "type", "lang", "text"]
        columns = [
            c for c in _col_order if any(str(row.get(c, "")).strip() for row in preview)
        ]

        # Compute pixel widths for fixed columns based on max content length.
        # 'text' fills remaining space (no fixed width).
        _ch_px = 8  # approximate px per character at small font size
        _col_min = {"id": 36, "type": 60, "lang": 42}  # absolute minimums
        col_widths = {}
        for col in columns:
            if col == "text":
                continue
            header_len = {"id": 1, "type": 4, "lang": 4}.get(col, len(col))
            max_val = max((len(str(row.get(col, ""))) for row in preview), default=0)
            px = max(max(max_val, header_len) * _ch_px + 16, _col_min.get(col, 40))
            col_widths[col] = f"{px}px"

        files.append(
            {
                "name": fname,
                "type": ftype,
                "badge": fbadge,
                "label": flabel,
                "entries": entries,
                "preview": preview,
                "columns": columns,
                "col_widths": col_widths,
            }
        )

    readme_html = None
    readme_path = folder / "README.md"
    if readme_path.is_file():
        try:
            import re as _re

            source = readme_path.read_text(encoding="utf-8")
            readme_html = md_lib.markdown(
                source,
                extensions=["fenced_code", "tables", "nl2br"],
            )
            # Sanitise: remove dangerous elements, event handlers, javascript: URIs.
            # Strip dangerous elements entirely
            readme_html = _re.sub(
                r"<(/?)(script|iframe|object|embed|form|base|meta|link|svg|math)(\s[^>]*)?/?>",
                lambda m: f"&lt;{m.group(1)}{m.group(2)}&gt;",
                readme_html,
                flags=_re.IGNORECASE,
            )
            # Strip inline event handler attributes (on*=...)
            readme_html = _re.sub(
                r'\s+on\w+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]*)',
                "",
                readme_html,
                flags=_re.IGNORECASE,
            )
            # Replace javascript: and data: URIs in href/src attributes
            readme_html = _re.sub(
                r'(href|src)\s*=\s*"(javascript|data):[^"]*"',
                r'\1="#"',
                readme_html,
                flags=_re.IGNORECASE,
            )
            readme_html = _re.sub(
                r"(href|src)\s*=\s*'(javascript|data):[^']*'",
                r"\1='#'",
                readme_html,
                flags=_re.IGNORECASE,
            )
        except Exception:
            readme_html = None

    scripts = sorted(
        path.name
        for path in folder.iterdir()
        if path.is_file() and path.suffix == ".py"
    )
    return {
        "path": str(folder),
        "files": files,
        "scripts": scripts,
        "readme_html": readme_html,
    }


def _load_dataset_entries(dataset_name: str, page: int = 1) -> dict | None:
    """Read a dataset JSONL from CWD/datasets/ and return a paginated result."""
    # Prevent path traversal: resolve and verify path stays inside datasets/
    datasets_dir = (Path(os.getcwd()) / "datasets").resolve()
    path = (datasets_dir / dataset_name).resolve()
    if not path.is_relative_to(datasets_dir):
        return None  # reject traversal attempts
    if not path.is_file():
        return None
    try:
        rows = read_jsonl_file(str(path))
    except Exception:
        return None

    total = len(rows)
    total_pages = max(1, (total + _DATASET_PAGE - 1) // _DATASET_PAGE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * _DATASET_PAGE
    page_rows = rows[offset : offset + _DATASET_PAGE]

    # Normalise entries: resolve content field, keep all relevant keys
    _col_order = [
        "id",
        "jailbreak_type",
        "instruction_type",
        "lang",
        "plugin",
        "position",
        "content",
    ]
    normalised = []
    for i, r in enumerate(page_rows):
        normalised.append(
            {
                "id": r.get("id", "—"),
                "jailbreak_type": r.get("jailbreak_type", ""),
                "instruction_type": r.get("instruction_type", ""),
                "lang": r.get("lang", ""),
                "plugin": r.get("plugin", ""),
                "position": r.get("position", ""),
                "content": str(r.get("content") or r.get("text") or "")[:400],
                "line_no": offset + i,
            }
        )

    # Detect which columns have at least one non-empty value across ALL rows (not just page)
    full_sample = rows[:500]  # sample up to 500 rows for column detection
    columns = [
        c
        for c in _col_order
        if any(
            str(
                r.get("content") or r.get("text") or ""
                if c == "content"
                else r.get(c, "")
            ).strip()
            for r in full_sample
        )
    ]

    # Compute pixel widths for fixed columns
    _col_labels = {
        "id": "#",
        "jailbreak_type": "Jailbreak",
        "instruction_type": "Instruction",
        "lang": "Lang",
        "plugin": "Plugin",
        "position": "Position",
        "content": "Content",
    }
    _col_min = {
        "id": 36,
        "lang": 42,
        "position": 60,
        "plugin": 60,
        "jailbreak_type": 70,
        "instruction_type": 80,
    }
    _ch_px = 8
    col_widths = {}
    for col in columns:
        if col == "content":
            continue
        header_len = len(_col_labels[col])
        max_val = max(
            (
                len(
                    str(
                        r.get("content") or r.get("text") or ""
                        if col == "content"
                        else r.get(col, "")
                    )
                )
                for r in full_sample
            ),
            default=0,
        )
        px = max(max(max_val, header_len) * _ch_px + 16, _col_min.get(col, 40))
        col_widths[col] = f"{px}px"

    return {
        "total": total,
        "total_pages": total_pages,
        "page": page,
        "entries": normalised,
        "columns": columns,
        "col_widths": col_widths,
        "col_labels": _col_labels,
    }


# ── Routes ────────────────────────────────────────────────────────────────────


@generate_bp.route("/")
@generate_bp.route("")
def index() -> Response:
    """Redirect to the generate run page."""
    return redirect(url_for("generate.run"))


@generate_bp.route("/seeds")
def seeds() -> str:
    """Render the seed folder browser."""
    return render_template("generate/seeds.html", seeds=_collect_seeds_with_meta())


@generate_bp.route("/plugins")
def plugins() -> str:
    """Render the plugin workshop — build a pipeline, enter input, see output."""
    return render_template(
        "generate/plugins.html",
        plugins=_collect_plugins_detail(),
    )


@generate_bp.route("/plugins/run", methods=["POST"])
def plugins_run() -> Response:
    """Execute a plugin pipeline against a user-supplied input text.

    Expects JSON body:
        pipeline         — pipe-separated plugin names, e.g. "base64|rot13"
        plugin_options   — semicolon/newline-separated "plugin:key=val" strings
        input_text       — text to transform
        exclude_patterns — newline-separated regex strings to exclude from transformation

    Returns JSON:
        {outputs: [str], count: int, error: str|null}
    """
    from flask import jsonify
    from spikee.generator import apply_plugin, load_plugins, parse_plugin_options

    data = request.get_json(silent=True) or {}
    pipeline_str = (data.get("pipeline") or "").strip()
    options_raw = (data.get("plugin_options") or "").strip()
    input_text = data.get("input_text", "")
    exclude_raw = (data.get("exclude_patterns") or "").strip()

    # Parse exclude patterns — one regex per non-empty line
    exclude_patterns = [
        ln.strip() for ln in exclude_raw.splitlines() if ln.strip()
    ] or None

    if not pipeline_str:
        return jsonify({"outputs": [], "count": 0, "error": "No plugins specified."})
    if input_text == "":
        return jsonify({"outputs": [], "count": 0, "error": "Input text is empty."})

    # Normalise options — accept newlines or semicolons as separators
    options_normalised = ";".join(
        ln.strip() for ln in options_raw.replace(";", "\n").splitlines() if ln.strip()
    )
    plugin_option_map = parse_plugin_options(options_normalised)

    try:
        # pipeline_str is already in the |-separated format load_plugins expects
        plugins_loaded = load_plugins([pipeline_str])
    except SystemExit:
        return jsonify(
            {
                "outputs": [],
                "count": 0,
                "error": f"Failed to load plugin(s): {pipeline_str}",
            }
        )
    except Exception as exc:
        return jsonify({"outputs": [], "count": 0, "error": str(exc)})

    if not plugins_loaded:
        return jsonify({"outputs": [], "count": 0, "error": "No plugins loaded."})

    plugin_name, plugin_module = plugins_loaded[0]

    try:
        results = apply_plugin(
            plugin_name,
            plugin_module,
            input_text,
            exclude_patterns=exclude_patterns,
            plugin_option_map=plugin_option_map,
        )
    except Exception as exc:
        return jsonify({"outputs": [], "count": 0, "error": str(exc)})

    # Coerce Content objects to plain strings
    from spikee.utilities.hinting import get_content

    outputs = [str(get_content(r)) for r in results]

    return jsonify({"outputs": outputs, "count": len(outputs), "error": None})


@generate_bp.route("/datasets/<path:dataset_name>", methods=["DELETE"])
def dataset_delete(dataset_name: str) -> Response:
    """Delete an entire dataset file."""
    datasets_dir = (Path(os.getcwd()) / "datasets").resolve()
    file_path = _resolve_editable_path(dataset_name, datasets_dir)
    if file_path is None or not file_path.is_file():
        abort(404)
    file_path.unlink()
    return "", 200


@generate_bp.route("/datasets/<path:dataset_name>/clone", methods=["POST"])
def dataset_clone(dataset_name: str) -> Response:
    """Clone a dataset file to a new name."""
    from flask import jsonify

    datasets_dir = (Path(os.getcwd()) / "datasets").resolve()
    file_path = _resolve_editable_path(dataset_name, datasets_dir)
    if file_path is None or not file_path.is_file():
        abort(404)
    data = request.get_json(silent=True) or {}
    new_name = data.get("new_name", "").strip()
    if not new_name:
        abort(400, description="new_name is required.")
    if not new_name.endswith(".jsonl"):
        new_name += ".jsonl"
    new_path = (datasets_dir / new_name).resolve()
    if not new_path.is_relative_to(datasets_dir):
        abort(400, description="Invalid new dataset name.")
    if new_path.exists():
        abort(409, description="A dataset with that name already exists.")
    import shutil

    shutil.copy2(file_path, new_path)
    return jsonify(
        {"url": url_for("generate.dataset_detail", dataset_name=new_name)}
    ), 201


@generate_bp.route("/datasets/<path:dataset_name>/rename", methods=["POST"])
def dataset_rename(dataset_name: str) -> Response:
    """Rename a dataset file within datasets/."""
    from flask import jsonify

    datasets_dir = (Path(os.getcwd()) / "datasets").resolve()
    file_path = _resolve_editable_path(dataset_name, datasets_dir)
    if file_path is None or not file_path.is_file():
        abort(404)
    data = request.get_json(silent=True) or {}
    new_name = (data.get("new_name") or "").strip()
    if not new_name:
        abort(400, description="new_name is required.")
    if not new_name.endswith(".jsonl"):
        new_name += ".jsonl"
    new_path = (datasets_dir / new_name).resolve()
    if not new_path.is_relative_to(datasets_dir):
        abort(400, description="Invalid new dataset name.")
    if new_path.exists():
        abort(409, description="A dataset with that name already exists.")
    try:
        file_path.rename(new_path)
    except FileExistsError:
        abort(409, description="A dataset with that name already exists.")
    return jsonify(
        {"url": url_for("generate.dataset_detail", dataset_name=new_name)}
    ), 200


@generate_bp.route("/seeds/<seed_name>/clone", methods=["POST"])
def seed_clone(seed_name: str) -> Response:
    """Clone an entire seed folder to a new name inside datasets/."""
    from flask import jsonify

    import shutil

    datasets_dir = (Path(os.getcwd()) / "datasets").resolve()
    src_dir = _resolve_seed_dir(seed_name, datasets_dir)
    if src_dir is None or not src_dir.is_dir():
        abort(404)
    data = request.get_json(silent=True) or {}
    new_name = (data.get("new_name") or "").strip()
    if not new_name:
        abort(400, description="new_name is required.")
    new_dir = _resolve_seed_dir(new_name, datasets_dir)
    if new_dir is None:
        abort(400, description="Invalid new seed name.")
    if new_dir.exists():
        abort(409, description="A seed folder with that name already exists.")
    shutil.copytree(src_dir, new_dir)
    return jsonify({"url": url_for("generate.seed_detail", seed_name=new_name)}), 201


@generate_bp.route("/seeds/<seed_name>/rename", methods=["POST"])
def seed_rename(seed_name: str) -> Response:
    """Rename an entire seed folder within datasets/."""
    from flask import jsonify

    datasets_dir = (Path(os.getcwd()) / "datasets").resolve()
    src_dir = _resolve_seed_dir(seed_name, datasets_dir)
    if src_dir is None or not src_dir.is_dir():
        abort(404)
    data = request.get_json(silent=True) or {}
    new_name = (data.get("new_name") or "").strip()
    if not new_name:
        abort(400, description="new_name is required.")
    new_dir = _resolve_seed_dir(new_name, datasets_dir)
    if new_dir is None:
        abort(400, description="Invalid new seed name.")
    if new_dir.exists():
        abort(409, description="A seed folder with that name already exists.")
    try:
        src_dir.rename(new_dir)
    except FileExistsError:
        abort(409, description="A seed folder with that name already exists.")
    return jsonify({"url": url_for("generate.seed_detail", seed_name=new_name)}), 200


@generate_bp.route("/seeds/<seed_name>", methods=["DELETE"])
def seed_delete(seed_name: str) -> Response:
    """Delete an entire seed folder from datasets/."""
    import shutil

    datasets_dir = (Path(os.getcwd()) / "datasets").resolve()
    seed_dir = _resolve_seed_dir(seed_name, datasets_dir)
    if seed_dir is None or not seed_dir.is_dir():
        abort(404)
    shutil.rmtree(seed_dir)
    return "", 200


@generate_bp.route("/seeds/<seed_name>")
def seed_detail(seed_name: str) -> str:
    """Render the detail view for a seed folder, showing all contained files."""
    detail = _load_seed_detail(seed_name)
    if detail is None:
        abort(404, description=f"Seed folder '{seed_name}' not found.")
    datasets_dir = (Path(os.getcwd()) / "datasets").resolve()
    is_local = Path(detail["path"]).resolve().is_relative_to(datasets_dir)
    return render_template(
        "generate/seed_detail.html",
        seed_name=seed_name,
        detail=detail,
        is_local=is_local,
    )


@generate_bp.route("/seeds/<seed_name>/scripts/<script_name>", methods=["POST"])
def seed_script_run(seed_name: str, script_name: str) -> Response:
    """Run a local seed script as a background job with user-supplied arguments."""
    from spikee.viewer.job_queue import job_queue, spawn_job

    datasets_dir = (Path(os.getcwd()) / "datasets").resolve()
    seed_dir = _resolve_seed_dir(seed_name, datasets_dir)
    if seed_dir is None or not seed_dir.is_dir():
        abort(404)

    script_path = (seed_dir / script_name).resolve()
    if (
        script_path.parent != seed_dir
        or script_path.suffix != ".py"
        or not script_path.is_file()
    ):
        abort(404, description="Script not found in seed folder.")

    command_text = (request.form.get("command") or "").strip()
    if not command_text:
        command_text = f"python datasets/{seed_name}/{script_name}"
    try:
        tokens = shlex.split(command_text, posix=False)
    except ValueError as exc:
        abort(400, description=f"Invalid command: {exc}")

    script_token_index = next(
        (
            i
            for i, token in enumerate(tokens)
            if Path(token.strip('"')).name == script_name
        ),
        None,
    )
    if script_token_index is None:
        abort(400, description=f"Command must include {script_name}.")

    script_token = tokens[script_token_index].strip('"')
    requested_script = Path(script_token)
    if requested_script.is_absolute():
        requested_path = requested_script.resolve()
    else:
        requested_path = (Path(os.getcwd()) / requested_script).resolve()
        if not requested_path.is_file():
            requested_path = (seed_dir / requested_script).resolve()
    if requested_path != script_path:
        abort(400, description="Command script must belong to this seed folder.")

    args = [sys.executable, str(script_path), *tokens[script_token_index + 1 :]]
    job = job_queue.create(
        type="script",
        name=f"Script: {seed_name}/{script_name}",
        args=args,
    )
    spawn_job(job)
    return redirect(url_for("jobs.detail", job_id=job.id))


@generate_bp.route("/datasets")
def datasets() -> str:
    """Render the dataset browser listing all generated datasets."""
    return render_template(
        "generate/datasets.html", datasets=_collect_datasets_with_meta()
    )


# ── File editor helpers ───────────────────────────────────────────────────────

_EDITABLE_EXTENSIONS = {".jsonl", ".toml"}


def _resolve_editable_path(rel_path: str, base_dir: Path) -> Path | None:
    """Resolve rel_path within base_dir; return None on traversal or bad extension."""
    try:
        resolved = (base_dir / rel_path).resolve()
    except Exception:
        return None
    if not resolved.is_relative_to(base_dir.resolve()):
        return None
    if resolved.suffix not in _EDITABLE_EXTENSIONS:
        return None
    return resolved


def _resolve_seed_dir(seed_name: str, base_dir: Path) -> Path | None:
    """Resolve a seed folder name within base_dir; None on traversal or bad name."""
    if not seed_name or "/" in seed_name or "\\" in seed_name or ".." in seed_name:
        return None
    try:
        resolved = (base_dir / seed_name).resolve()
    except Exception:
        return None
    if not resolved.is_relative_to(base_dir.resolve()):
        return None
    return resolved


def _file_stats(path: Path) -> dict:
    size = path.stat().st_size if path.exists() else 0
    return {"size_bytes": size, "size_kb": round(size / 1024, 1)}


def _atomic_write(path: Path, content: str) -> None:
    """Replace a file atomically using a temporary file in the same directory."""
    tmp = path.parent / f".{path.name}.tmp"
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _jsonl_rows(path: Path) -> list[dict]:
    """Read canonical JSONL rows, ignoring blank lines."""
    import json as _json

    rows = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                rows.append(_json.loads(line))
    return rows


def _write_jsonl_rows(path: Path, rows: list[dict]) -> None:
    """Atomically write JSON objects as one compact object per line."""
    import json as _json

    content = "".join(
        _json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in rows
    )
    _atomic_write(path, content)


def _parse_line_numbers(data: dict) -> list[int]:
    """Validate and normalize a bulk row index payload."""
    values = data.get("line_numbers")
    if not isinstance(values, list) or not values:
        abort(400, description="line_numbers must be a non-empty list.")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in values
    ):
        abort(400, description="line_numbers must contain non-negative integers.")
    if len(set(values)) != len(values):
        abort(400, description="line_numbers must not contain duplicates.")
    return values


# ── Line mutation routes ─────────────────────────────────────────────────────


@generate_bp.route("/seeds/<seed_name>/lines/<filename>", methods=["POST"])
def seed_delete_line(seed_name: str, filename: str) -> Response:
    """Delete selected JSONL rows from a local seed file."""
    datasets_dir = (Path(os.getcwd()) / "datasets").resolve()
    try:
        seed_folder = Path(str(resolve_seed_folder(f"datasets/{seed_name}")))
    except Exception:
        abort(404)
    if not seed_folder.resolve().is_relative_to(datasets_dir):
        abort(403)
    file_path = _resolve_editable_path(filename, seed_folder)
    if file_path is None or not file_path.is_file():
        abort(404)
    line_numbers = _parse_line_numbers(request.get_json(silent=True) or {})
    rows = _jsonl_rows(file_path)
    if any(line_no >= len(rows) for line_no in line_numbers):
        abort(404, description="One or more rows no longer exist.")
    _write_jsonl_rows(
        file_path, [row for i, row in enumerate(rows) if i not in line_numbers]
    )
    return Response(status=204)


@generate_bp.route("/datasets/<path:dataset_name>/lines", methods=["POST"])
def dataset_delete_line(dataset_name: str) -> Response:
    """Delete selected JSONL rows from a dataset file."""
    datasets_dir = (Path(os.getcwd()) / "datasets").resolve()
    file_path = _resolve_editable_path(dataset_name, datasets_dir)
    if file_path is None or not file_path.is_file():
        abort(404)
    line_numbers = _parse_line_numbers(request.get_json(silent=True) or {})
    rows = _jsonl_rows(file_path)
    if any(line_no >= len(rows) for line_no in line_numbers):
        abort(404, description="One or more rows no longer exist.")
    _write_jsonl_rows(
        file_path, [row for i, row in enumerate(rows) if i not in line_numbers]
    )
    return Response(status=204)


def _render_entry_editor(
    file_path: Path,
    filename: str,
    back_url: str,
    line_no: int | None,
    content: str | None = None,
    error: str | None = None,
    is_new: bool = False,
) -> str:
    import json as _json

    rows = _jsonl_rows(file_path)
    if is_new:
        line_no = len(rows)
        formatted = (
            content
            if content is not None
            else _json.dumps({}, indent=2, ensure_ascii=False)
        )
    else:
        if line_no is None or line_no < 0 or line_no >= len(rows):
            abort(404, description="JSONL row not found.")
        formatted = (
            content
            if content is not None
            else _json.dumps(rows[line_no], indent=2, ensure_ascii=False)
        )
    return render_template(
        "generate/edit_file.html",
        filename=filename,
        content=formatted,
        back_url=back_url,
        error=error,
        mode="entry",
        is_new=is_new,
        line_no=line_no,
        total_entries=len(rows),
        **_file_stats(file_path),
    )


def _entry_post(
    file_path: Path,
    line_no: int | None,
    is_new: bool,
    content: str,
    back_url: str,
    filename: str,
) -> Response | str:
    import json as _json

    try:
        value = _json.loads(content)
    except _json.JSONDecodeError as exc:
        return _render_entry_editor(
            file_path,
            filename,
            back_url,
            line_no,
            content,
            f"JSON error: {exc}",
            is_new,
        )
    if not isinstance(value, dict):
        return _render_entry_editor(
            file_path,
            filename,
            back_url,
            line_no,
            content,
            "An entry must be a JSON object.",
            is_new,
        )

    rows = _jsonl_rows(file_path)
    if is_new:
        rows.append(value)
    elif line_no is None or line_no < 0 or line_no >= len(rows):
        abort(404, description="JSONL row no longer exists.")
    else:
        rows[line_no] = value
    _write_jsonl_rows(file_path, rows)
    return redirect(back_url + "?saved=1")


def _seed_jsonl_path(seed_name: str, filename: str) -> Path:
    datasets_dir = (Path(os.getcwd()) / "datasets").resolve()
    try:
        seed_folder = Path(str(resolve_seed_folder(f"datasets/{seed_name}")))
    except Exception:
        abort(404)
    if not seed_folder.resolve().is_relative_to(datasets_dir):
        abort(403, description="Built-in seeds are not editable.")
    file_path = _resolve_editable_path(filename, seed_folder)
    if file_path is None or file_path.suffix != ".jsonl" or not file_path.is_file():
        abort(404)
    return file_path


@generate_bp.route(
    "/seeds/<seed_name>/entries/<int:line_no>/edit", methods=["GET", "POST"]
)
def seed_entry_edit(seed_name: str, line_no: int) -> Response | str:
    filename = request.args.get("filename", "")
    file_path = _seed_jsonl_path(seed_name, filename)
    back_url = url_for("generate.seed_detail", seed_name=seed_name)
    if request.method == "POST":
        return _entry_post(
            file_path,
            line_no,
            False,
            request.form.get("content", ""),
            back_url,
            filename,
        )
    return _render_entry_editor(file_path, filename, back_url, line_no)


@generate_bp.route("/seeds/<seed_name>/entries/<filename>/new", methods=["GET", "POST"])
def seed_entry_new(seed_name: str, filename: str) -> Response | str:
    file_path = _seed_jsonl_path(seed_name, filename)
    back_url = url_for("generate.seed_detail", seed_name=seed_name)
    if request.method == "POST":
        return _entry_post(
            file_path, None, True, request.form.get("content", ""), back_url, filename
        )
    return _render_entry_editor(file_path, filename, back_url, None, is_new=True)


def _dataset_jsonl_path(dataset_name: str) -> Path:
    datasets_dir = (Path(os.getcwd()) / "datasets").resolve()
    file_path = _resolve_editable_path(dataset_name, datasets_dir)
    if file_path is None or file_path.suffix != ".jsonl" or not file_path.is_file():
        abort(404)
    return file_path


@generate_bp.route(
    "/datasets/<path:dataset_name>/entries/<int:line_no>/edit", methods=["GET", "POST"]
)
def dataset_entry_edit(dataset_name: str, line_no: int) -> Response | str:
    file_path = _dataset_jsonl_path(dataset_name)
    back_url = url_for("generate.dataset_detail", dataset_name=dataset_name)
    if request.method == "POST":
        return _entry_post(
            file_path,
            line_no,
            False,
            request.form.get("content", ""),
            back_url,
            dataset_name,
        )
    return _render_entry_editor(file_path, dataset_name, back_url, line_no)


@generate_bp.route("/datasets/<path:dataset_name>/entries/new", methods=["GET", "POST"])
def dataset_entry_new(dataset_name: str) -> Response | str:
    file_path = _dataset_jsonl_path(dataset_name)
    back_url = url_for("generate.dataset_detail", dataset_name=dataset_name)
    if request.method == "POST":
        return _entry_post(
            file_path,
            None,
            True,
            request.form.get("content", ""),
            back_url,
            dataset_name,
        )
    return _render_entry_editor(file_path, dataset_name, back_url, None, is_new=True)


@generate_bp.route("/seeds/<seed_name>/edit/<filename>", methods=["GET", "POST"])
def seed_edit(seed_name: str, filename: str) -> Response | str:
    """Render the unchecked raw editor for a seed file."""
    datasets_dir = (Path(os.getcwd()) / "datasets").resolve()

    # Resolve the seed folder first so we can locate the file inside it.
    try:
        seed_folder = Path(str(resolve_seed_folder(f"datasets/{seed_name}")))
    except Exception:
        abort(404)

    # Reject built-in seeds (outside CWD/datasets/) and path traversal.
    if not seed_folder.resolve().is_relative_to(datasets_dir):
        abort(403, description="Built-in seeds are not editable.")

    file_path = _resolve_editable_path(filename, seed_folder)
    if file_path is None or not file_path.is_file():
        abort(404)

    back_url = url_for("generate.seed_detail", seed_name=seed_name)

    if request.method == "POST":
        content = request.form.get("content", "")
        _atomic_write(file_path, content)
        return redirect(back_url + "?saved=1")

    content = file_path.read_text(encoding="utf-8")
    stats = _file_stats(file_path)
    return render_template(
        "generate/edit_file.html",
        filename=filename,
        content=content,
        back_url=back_url,
        error=None,
        mode="raw",
        is_new=False,
        line_no=None,
        total_entries=None,
        **stats,
    )


# ── Dataset file editor ───────────────────────────────────────────────────────


@generate_bp.route("/datasets/<path:dataset_name>/edit", methods=["GET", "POST"])
def dataset_edit(dataset_name: str) -> Response | str:
    """Render the unchecked raw editor for a dataset JSONL."""
    datasets_dir = (Path(os.getcwd()) / "datasets").resolve()
    file_path = _resolve_editable_path(dataset_name, datasets_dir)
    if file_path is None or not file_path.is_file():
        abort(404)

    back_url = url_for("generate.dataset_detail", dataset_name=dataset_name)

    if request.method == "POST":
        content = request.form.get("content", "")
        _atomic_write(file_path, content)
        return redirect(back_url + "?saved=1")

    content = file_path.read_text(encoding="utf-8")
    stats = _file_stats(file_path)
    return render_template(
        "generate/edit_file.html",
        filename=dataset_name,
        content=content,
        back_url=back_url,
        error=None,
        mode="raw",
        is_new=False,
        line_no=None,
        total_entries=None,
        **stats,
    )


@generate_bp.route("/datasets/<path:dataset_name>")
def dataset_detail(dataset_name: str) -> str:
    """Render a paginated view of a single dataset's entries."""
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    result = _load_dataset_entries(dataset_name, page)
    if result is None:
        abort(404, description=f"Dataset '{dataset_name}' not found.")
    return render_template(
        "generate/dataset_detail.html",
        dataset_name=dataset_name,
        meta={"name": dataset_name, "entry_count": result["total"]},
        entries=result["entries"],
        page=result["page"],
        total_pages=result["total_pages"],
        total=result["total"],
        columns=result["columns"],
        col_widths=result["col_widths"],
        col_labels=result["col_labels"],
    )


@generate_bp.route("/run", methods=["GET"])
def run() -> str:
    """Render the dataset generation form."""
    return render_template(
        "generate/run.html",
        seeds=_collect_seeds_with_meta(),
        saved=session.get("generate_settings", {}),
    )


@generate_bp.route("/partials/plugins-list")
def plugins_list_partial() -> str:
    """HTMX partial — returns plugin button list HTML or a polling spinner."""
    if not _module_cache.is_type_ready("plugins"):
        return render_template(
            "partials/_picker_loading.html",
            target_id="plugin-list",
            poll_url="/generate/partials/plugins-list",
            label="plugins",
        )
    return render_template("partials/_plugins_list.html", plugins=_collect_plugins())


@generate_bp.route("/run", methods=["POST"])
def run_post() -> Response:
    """Handle dataset generation form submission, create a job, and redirect to its detail page."""
    try:
        form = GenerateForm.from_form(request.form)
    except FormValidationError as exc:
        abort(400, description=str(exc))
        return  # unreachable; satisfies type checkers

    # Persist form state for next visit (tag excluded — it's per-run)
    _excluded = {"tag"}
    saved: dict = {k: v for k, v in request.form.items() if k not in _excluded}
    saved["positions"] = request.form.getlist("positions")
    session["generate_settings"] = saved

    args = form.to_cli_args()
    job = job_queue.create(type="generate", name=form.job_name, args=args)
    spawn_job(job)
    return redirect(url_for("jobs.detail", job_id=job.id))
