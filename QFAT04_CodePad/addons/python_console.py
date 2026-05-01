"""
python_console.py  v0.3
Addon: Run Python scripts from the CodePad editor.

v0.2: Switched F5 from `shortcuts` hook to `run_handler` hook (since plugin
v1.0.18). This claims the Run action before the built-in "Save the script
first" dialog fires, so scripts run directly from the editor buffer without
needing to be saved.

Replaces the need for the QGIS built-in Python console. Runs the current
selection (if any) or the full editor content. Output goes to the CodePad
Console panel, errors to the Messages panel.

Scripts have access to iface, QgsProject, and other QGIS APIs.

Trigger: F5 (via run_handler) or toolbar button.
"""
__version__ = "0.5"

import sys
import io
import traceback

from qgis.core import QgsProject

# ---------------------------------------------------------------------------
# Script execution
# ---------------------------------------------------------------------------
def _get_run_text(page):
    """Return selected text if any, otherwise full editor text."""
    if not page:
        return None, "selection"
    editor = page.editor
    if page.editor_kind == "scintilla":
        sel = editor.selectedText()
        if sel:
            return sel, "selection"
    else:
        cursor = editor.textCursor()
        if cursor.hasSelection():
            return cursor.selectedText(), "selection"
    text = page.editor.editor_text()
    return text, "file"


def _build_globals(dock):
    """Build the globals dict for exec(), mimicking QGIS Python console.
    Imports everything the built-in console makes available."""
    g = {"__builtins__": __builtins__}

    # Standard library
    import os, sys, math, re, json, glob, shutil, pathlib
    g.update({"os": os, "sys": sys, "math": math, "re": re,
              "json": json, "glob": glob, "shutil": shutil, "pathlib": pathlib})

    # iface
    try:
        g["iface"] = dock.iface
    except Exception:
        pass

    # qgis.core — import *
    try:
        import qgis.core
        g["qgis"] = __import__("qgis")
        for name in dir(qgis.core):
            if not name.startswith("_"):
                g[name] = getattr(qgis.core, name)
    except Exception:
        pass

    # qgis.gui — import *
    try:
        import qgis.gui
        for name in dir(qgis.gui):
            if not name.startswith("_"):
                g[name] = getattr(qgis.gui, name)
    except Exception:
        pass

    # qgis.utils
    try:
        import qgis.utils
        g["qgis.utils"] = qgis.utils
    except Exception:
        pass

    # PyQt5 / qgis.PyQt — common modules
    try:
        from qgis.PyQt import QtCore, QtGui, QtWidgets
        g["QtCore"] = QtCore
        g["QtGui"] = QtGui
        g["QtWidgets"] = QtWidgets
        # Common classes directly
        for mod in (QtCore, QtGui, QtWidgets):
            for name in dir(mod):
                if name.startswith("Q"):
                    g[name] = getattr(mod, name)
    except Exception:
        pass

    # processing
    try:
        import processing
        g["processing"] = processing
    except Exception:
        pass

    return g


def _run_script(dock):
    """Run the current selection or full editor content as Python."""
    page = dock.current_page()
    if not page:
        dock.messages.append("[Python Runner] No file open.")
        return

    text, source = _get_run_text(page)
    if not text or not text.strip():
        dock.messages.append("[Python Runner] Nothing to run.")
        return

    script_name = page.path if page.path else "<untitled>"

    old_stdout = sys.stdout
    old_stderr = sys.stderr
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    sys.stdout = stdout_capture
    sys.stderr = stderr_capture

    g = _build_globals(dock)

    try:
        code = compile(text, script_name, "exec")
        exec(code, g)
    except SyntaxError as e:
        err_msg = "SyntaxError: %s (line %s)" % (e.msg, e.lineno)
        stderr_capture.write(err_msg + "\n")
    except Exception:
        tb = traceback.format_exc()
        stderr_capture.write(tb)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    stdout_text = stdout_capture.getvalue()
    if stdout_text:
        for line in stdout_text.rstrip("\n").split("\n"):
            dock.console.append(line)

    stderr_text = stderr_capture.getvalue()
    if stderr_text:
        dock.messages.append("[Python Runner] --- Error running %s (%s) ---"
                             % (script_name, source))
        for line in stderr_text.rstrip("\n").split("\n"):
            dock.messages.append(line)


# ---------------------------------------------------------------------------
# Run hook — claim F5 before save-first dialog
# ---------------------------------------------------------------------------
def _run_handler(dock, page):
    """Claim the Run action: bypass save-first dialog, run from buffer."""
    _run_script(dock)
    return True


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
def register():
    return {
        "id": "python_console",
        "name": "Python Console  v" + __version__,
        "description": "Run Python scripts from the editor without saving. "
                       "Selection or full file. Output to Console, errors to Messages. "
                       "Trigger: F5 (run_handler) or toolbar button.",
        "core": False,
        "builtin": True,
        "hooks": {
            "run_handler": _run_handler,
            "toolbar_button": [
                {
                    "name": "Run Python (F5)",
                    "callback": lambda dock: _run_script(dock),
                },
            ],
        },
    }
