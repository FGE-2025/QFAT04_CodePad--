"""
qfat04_runners.py
Execution Engine.  RunController wraps QProcess.
"""
import os
import shutil
from qgis.PyQt.QtCore import QProcess, QFileInfo
from .qfat04_config import get_run_exts


def _resolve_powershell():
    """Find powershell.exe. Honors user setting, then PATH, then common full paths."""
    from qgis.PyQt.QtCore import QSettings
    configured = QSettings().value("QFAT/QFAT04/interpreter_powershell", "", type=str).strip()
    if configured and os.path.exists(configured):
        return configured
    # Try PATH
    p = shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh.exe")
    if p:
        return p
    # Fallback to common full paths
    candidates = [
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        r"C:\Program Files\PowerShell\7\pwsh.exe",
        os.path.expandvars(r"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "powershell.exe"  # last resort — will fail with WinError 2

class RunController:
    def __init__(self):
        self.process = None

    def is_running(self):
        return (
            self.process is not None
            and self.process.state() != QProcess.NotRunning
        )

    def start(self, path, on_stdout, on_stderr, on_finished):
        ext = os.path.splitext(path)[1].lower()
        run_exts = get_run_exts()
        if ext not in run_exts:
            raise ValueError("Extension '%s' is not configured as runnable.\n"
                             "Runnable extensions: %s" % (ext, " ".join(sorted(run_exts))))
        self.process = QProcess()
        work_dir     = QFileInfo(path).absolutePath()
        self.process.setWorkingDirectory(work_dir)

        self.process.readyReadStandardOutput.connect(
            lambda: on_stdout(bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace"))
        )
        self.process.readyReadStandardError.connect(
            lambda: on_stderr(bytes(self.process.readAllStandardError()).decode("utf-8", "replace"))
        )
        self.process.finished.connect(on_finished)

        win_path = os.path.normpath(path)
        program, args = self._resolve_command(ext, win_path)

        self.process.start(program, args)
        return program, args, work_dir

    def _resolve_command(self, ext, path):
        """Return (program, args) for a given file extension."""
        from qgis.PyQt.QtCore import QSettings
        s = QSettings()
        if ext in {".cmd", ".bat"}:
            return "cmd.exe", ["/c", "call", path]
        elif ext == ".ps1":
            ps = _resolve_powershell()
            return ps, ["-ExecutionPolicy", "Bypass", "-File", path]
        elif ext in {".py", ".pyw"}:
            configured = s.value("QFAT/QFAT04/interpreter_python", "", type=str).strip()
            python = configured or shutil.which("python3") or shutil.which("python") or "python"
            return python, ["-u", path]
        elif ext in {".r"}:
            configured = s.value("QFAT/QFAT04/interpreter_r", "", type=str).strip()
            rscript = configured or shutil.which("Rscript") or "Rscript"
            return rscript, ["--vanilla", path]
        else:
            return path, []

    def stop(self):
        if self.is_running():
            self.process.kill()
