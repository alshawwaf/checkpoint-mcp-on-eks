"""Line-based progress reporter for the long-running commands.

Deliberately simpler than the AgentCore project's full-screen UI: a numbered
step checklist with per-step timers, colour when stdout is a terminal, and a
plain transcript tee'd to ~/.chkpmcpeks/logs/ (ANSI stripped) for every run.
Opt out of colour with --plain, CHKP_UI=plain, or NO_COLOR; force it with CHKP_UI=color.
"""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime

from . import awsutil

FORCE_PLAIN = False
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

C_A = "\x1b[38;2;255;45;149m"     # Check Point magenta
C_B = "\x1b[38;2;122;60;170m"     # violet
C_OK = "\x1b[38;2;46;204;113m"
C_ERR = "\x1b[38;2;220;60;60m"
C_WARN = "\x1b[38;2;252;177;23m"
C_MUTED = "\x1b[38;2;128;132;150m"
BOLD = "\x1b[1m"
RESET = "\x1b[0m"


def color_wanted():
    if FORCE_PLAIN or os.environ.get("CHKP_UI") == "plain" or os.environ.get("NO_COLOR"):
        return False
    return os.environ.get("CHKP_UI") == "color" or sys.stdout.isatty()


def c(color, text):
    return f"{color}{text}{RESET}" if color_wanted() else text


def log_dir():
    base = os.environ.get("CHKP_LOG_DIR") or os.path.join(os.path.expanduser("~"), ".chkpmcpeks", "logs")
    os.makedirs(base, exist_ok=True)
    return base


class Reporter:
    """Usage:
        rep = Reporter("deploy", ["Preflight", "Terraform", ...], context="acct · region")
        rep.begin()            # next step
        log("detail")          # routed to the transcript (and the screen)
        rep.warn() / rep.fail()
        rep.close(ok, summary_lines)
    """

    def __init__(self, command, steps, context=""):
        self.command, self.steps, self.context = command, list(steps), context
        self.i = -1
        self.t0 = time.time()
        self.step_t0 = None
        self.status = {}
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.log_path = os.path.join(log_dir(), f"{command}-{stamp}.log")
        self._fh = open(self.log_path, "w", encoding="utf-8")  # noqa: SIM115
        awsutil.set_log_sink(self._sink)
        title = f"◆ chkpmcpeks · {command}"
        self._emit(c(BOLD + C_A, title) + (c(C_MUTED, f"   {context}") if context else ""))
        self._emit(c(C_MUTED, f"  transcript: {self.log_path}"))

    def _emit(self, line):
        print(line, flush=True)
        self._fh.write(_ANSI.sub("", line) + "\n")
        self._fh.flush()

    def _sink(self, msg):
        for line in str(msg).splitlines() or [""]:
            self._emit(c(C_MUTED, "    │ ") + line)

    def _close_step(self, mark=None):
        if self.i >= 0 and self.i not in self.status:
            self.status[self.i] = mark or "ok"
            dt = time.time() - (self.step_t0 or time.time())
            glyph = {"ok": c(C_OK, "✔"), "warn": c(C_WARN, "▲"), "fail": c(C_ERR, "✖")}[self.status[self.i]]
            self._emit(f"  {glyph} {self.steps[self.i]}  {c(C_MUTED, f'{dt:.0f}s')}")

    def begin(self, label=None):
        self._close_step()
        self.i += 1
        if self.i >= len(self.steps):
            self.steps.append(label or f"step {self.i + 1}")
        elif label:
            self.steps[self.i] = label
        self.step_t0 = time.time()
        self._emit(c(C_B, f"  [{self.i + 1}/{len(self.steps)}] ") + c(BOLD, self.steps[self.i]))

    def set_context(self, context):
        self.context = context
        self._emit(c(C_MUTED, f"  {context}"))

    def warn(self):
        self._close_step("warn")

    def fail(self):
        self._close_step("fail")

    def close(self, ok=True, summary=None):
        self._close_step()
        awsutil.set_log_sink(None)
        total = time.time() - self.t0
        banner = c(C_OK, "✔ DONE") if ok else c(C_ERR, "✖ FAILED")
        self._emit("")
        self._emit(f"{banner}  {c(C_MUTED, f'{self.command} · {total / 60:.1f} min')}")
        for line in summary or []:
            self._emit(line)
        self._fh.close()
