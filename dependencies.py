# -*- coding: utf-8 -*-
"""
Checks for the plugin's Python dependencies and installs missing ones.

Packages are installed with ``pip install --target`` into a folder inside the
QGIS profile, so no administrator rights are needed and system Pythons that
refuse ``pip install`` (PEP 668) are left untouched.
"""

import html
import importlib
import os
import shlex
import subprocess
import sys

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QProcess, QProcessEnvironment
from qgis.PyQt.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QPlainTextEdit,
                                 QProgressBar, QVBoxLayout)

# mcp 2.x renamed FastMCP to MCPServer; the plugin is written against 1.x.
# 1.8 added the streamable HTTP transport.
REQUIREMENTS = ["mcp>=1.8,<2"]


def dependencies_dir():
    """Folder that holds the installed packages, one per Python minor version."""
    return os.path.join(
        QgsApplication.qgisSettingsDirPath(), "python", "dependencies", "qmcp",
        "py{}{}".format(*sys.version_info[:2]))


def add_dependencies_to_path():
    path = dependencies_dir()
    if os.path.isdir(path) and path not in sys.path:
        # In front, so a system-wide mcp 2.x does not shadow the pinned 1.x
        sys.path.insert(0, path)
        importlib.invalidate_caches()


def missing_dependencies():
    """Return a description of what is missing, or None if everything imports."""
    add_dependencies_to_path()
    try:
        from mcp.server.fastmcp import FastMCP
        import uvicorn  # noqa: F401
        if not hasattr(FastMCP, "streamable_http_app"):
            raise ImportError("installed mcp is too old (streamable HTTP needs mcp>=1.8)")
    except ImportError as e:
        # Forget partially imported modules (e.g. an incompatible mcp) so a
        # later retry picks up freshly installed packages
        for name in list(sys.modules):
            if name in ("mcp", "uvicorn") or name.startswith(("mcp.", "uvicorn.")):
                del sys.modules[name]
        return str(e)
    return None


def python_executable():
    """Find the Python interpreter QGIS is running on.

    Inside QGIS sys.executable is usually the QGIS binary, not Python.
    """
    if sys.platform == "win32":
        names = ["python.exe", "python3.exe"]
        dirs = [sys.exec_prefix, os.path.dirname(sys.executable)]
    else:
        names = ["python{}.{}".format(*sys.version_info[:2]), "python3", "python"]
        dirs = [os.path.join(sys.exec_prefix, "bin"), os.path.dirname(sys.executable)]

    wanted = "{}.{}".format(*sys.version_info[:2])
    for directory in dirs:
        for name in names:
            candidate = os.path.join(directory, name)
            if not os.path.isfile(candidate):
                continue
            try:
                version = subprocess.run(
                    [candidate, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                    capture_output=True, text=True, timeout=15).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                continue
            # Packages with compiled parts must match QGIS' Python version
            if version == wanted:
                return candidate
    return None


class DependencyInstallDialog(QDialog):
    """Asks to install the missing packages and shows pip's progress."""

    def __init__(self, reason, parent=None):
        super().__init__(parent)
        self.setWindowTitle("QMCP - Install dependencies")
        self.setMinimumWidth(560)
        self.process = None
        self.python = python_executable()
        self.target = dependencies_dir()

        self.messageLabel = QLabel(
            "QMCP needs the following Python packages, which are not installed:"
            "<br><b>{}</b><br><br>They will be installed into:<br><code>{}</code>"
            .format(html.escape(", ".join(REQUIREMENTS)), html.escape(self.target)))
        self.messageLabel.setWordWrap(True)
        self.messageLabel.setToolTip(reason)

        self.statusLabel = QLabel()
        self.statusLabel.setWordWrap(True)
        self.progressBar = QProgressBar()
        self.progressBar.setVisible(False)
        self.progressBar.setTextVisible(False)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setVisible(False)
        self.log.setMinimumHeight(220)

        self.buttons = QDialogButtonBox()
        self.installButton = self.buttons.addButton("Install", QDialogButtonBox.AcceptRole)
        self.closeButton = self.buttons.addButton(QDialogButtonBox.Cancel)
        self.installButton.clicked.connect(self.install)
        self.closeButton.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.messageLabel)
        layout.addWidget(self.statusLabel)
        layout.addWidget(self.progressBar)
        layout.addWidget(self.log)
        layout.addWidget(self.buttons)

        if self.python is None:
            self.installButton.setEnabled(False)
            self.statusLabel.setText(
                "Could not find the Python interpreter used by QGIS. Install the "
                "packages manually with that interpreter:<br><code>python -m pip install "
                "--target \"{}\" {}</code>".format(html.escape(self.target), html.escape(" ".join(
                    '"{}"'.format(r) for r in REQUIREMENTS))))

    def install(self):
        os.makedirs(self.target, exist_ok=True)
        args = ["-m", "pip", "install", "--upgrade", "--disable-pip-version-check",
                "--no-input", "--progress-bar", "off", "--target", self.target] + REQUIREMENTS

        self.installButton.setEnabled(False)
        self.closeButton.setText("Cancel")
        self.progressBar.setVisible(True)
        self.progressBar.setRange(0, 0)  # pip does not report an overall total
        self.log.setVisible(True)
        self.resize(self.width(), max(self.height(), self.sizeHint().height()))
        self.log.appendPlainText("$ " + " ".join(shlex.quote(a) for a in [self.python] + args))
        self.statusLabel.setText("Starting pip...")

        self.process = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        self.process.setProcessEnvironment(env)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._readOutput)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._processError)
        self.process.start(self.python, args)

    def _readOutput(self):
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        for line in text.splitlines():
            if not line.strip():
                continue
            self.log.appendPlainText(line)
            self._updateStatus(line.strip())

    def _updateStatus(self, line):
        if line.startswith("Collecting "):
            self.statusLabel.setText("Resolving " + line.split()[1] + "...")
        elif line.startswith("Downloading "):
            self.statusLabel.setText("Downloading " + os.path.basename(line.split()[1]) + "...")
        elif line.startswith("Installing collected packages:"):
            count = len(line.split(":", 1)[1].split(","))
            self.statusLabel.setText("Installing {} packages...".format(count))

    def _processError(self, error):
        if error == QProcess.FailedToStart:
            self._fail("Could not run {}".format(self.python))

    def _finished(self, exitCode, exitStatus):
        if self.process is None:
            return
        self.process = None
        if exitStatus != QProcess.NormalExit or exitCode != 0:
            hint = ""
            if "No module named pip" in self.log.toPlainText():
                hint = (" pip is not available for QGIS' Python; on Debian/Ubuntu install it "
                        "with <code>sudo apt install python3-pip</code>.")
            self._fail("Installation failed (exit code {}).{} See the log for details."
                       .format(exitCode, hint))
            return

        self.progressBar.setRange(0, 1)
        self.progressBar.setValue(1)
        reason = missing_dependencies()
        if reason is None:
            self.statusLabel.setText("Dependencies installed.")
            self.accept()
        else:
            # Usually an older copy of a shared package (e.g. pydantic) was
            # already imported by QGIS or another plugin
            self.statusLabel.setText(
                "Packages were installed, but could not be loaded in this session ({}). "
                "Please restart QGIS.".format(reason))
            self.closeButton.setText("Close")

    def _fail(self, message):
        self.progressBar.setRange(0, 1)
        self.progressBar.setValue(0)
        self.statusLabel.setText(message)
        self.installButton.setText("Retry")
        self.installButton.setEnabled(True)
        self.closeButton.setText("Close")
        self.process = None

    def reject(self):
        if self.process is not None:
            process, self.process = self.process, None
            process.kill()
            process.waitForFinished(3000)
        super().reject()


def ensure_dependencies(parent=None):
    """Return True when dependencies are available, offering to install them if not."""
    reason = missing_dependencies()
    if reason is None:
        return True
    return DependencyInstallDialog(reason, parent).exec_() == QDialog.Accepted
