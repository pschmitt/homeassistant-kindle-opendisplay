"""Exec the launcher with reload signals enabled even after nohup."""

import os
import signal
import sys
from pathlib import Path

for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
    signal.signal(signum, signal.SIG_DFL)

launcher = Path(__file__).resolve().with_name("start")
os.environ["OPENDISPLAY_SIGNALS_READY"] = "1"
os.execv(launcher, [str(launcher), *sys.argv[1:]])
