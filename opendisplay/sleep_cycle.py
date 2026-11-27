"""Run OpenDisplay with optional RTC-backed suspend cycles."""

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from settings import load_settings

RTC = Path("/sys/class/rtc/rtc1")
POWER_STATE = Path("/sys/power/state")
EXTERNAL_POWER = Path("/sys/class/power_supply/bd71827_ac/online")
WIFI_DISABLED = Path("/mnt/us/linux/wifi.off")
WIFI_INTERFACE = Path("/sys/class/net/wlan0")
DHCP_PID = Path("/run/udhcpc.wlan0.pid")
FRAME = Path("frame.bin")
PREVENT_SLEEP = Path("prevent-sleep")
SESSION_LOCK = Path("/run/opendisplay-session.lock")
SESSION_GRACE_SECONDS = 8
WAKE_RECORD = Path("/run/opendisplay-last-wake")


def frame_stamp():
    """Return the last committed frame timestamp if present."""
    try:
        return FRAME.stat().st_mtime_ns
    except FileNotFoundError:
        return None


def sleep_allowed(settings):
    """Honor the persistent switch and external-power policy."""
    if PREVENT_SLEEP.exists():
        return False
    return (
        not settings.stay_awake_on_external_power
        or EXTERNAL_POWER.read_text().strip() == "0"
    )


def suspend(settings, stopping):
    """Arm the wake-capable SNVS clock and suspend on the same boot."""
    if stopping() or not sleep_allowed(settings):
        return False
    if (RTC / "device/power/wakeup").read_text().strip() != "enabled":
        raise RuntimeError("SNVS RTC wake is disabled")
    alarm = RTC / "wakealarm"
    if alarm.read_text().strip():
        raise RuntimeError("SNVS RTC already has an alarm")
    deadline = int((RTC / "since_epoch").read_text()) + settings.sleep_for_seconds
    alarm.write_text(f"{deadline}\n")
    try:
        if int(alarm.read_text()) != deadline:
            raise RuntimeError("SNVS RTC did not accept the wake alarm")
        if stopping() or not sleep_allowed(settings):
            return False
        print("OpenDisplay entering timed suspend", flush=True)
        before = time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()
        POWER_STATE.write_text("mem\n")
        suspended = time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic() - before
        print(f"OpenDisplay resumed after {suspended:.2f}s suspended", flush=True)
        if suspended >= 1:
            staged = WAKE_RECORD.with_suffix(".tmp")
            staged.write_text(json.dumps([int(time.time()), round(suspended, 2)]))
            staged.replace(WAKE_RECORD)
        return True
    finally:
        alarm.write_text("0\n")


def restore_wifi():
    """Replace the pre-suspend DHCP client when wlan0 lost its IPv4 address."""
    if WIFI_DISABLED.exists() or not WIFI_INTERFACE.exists():
        return
    address = subprocess.run(
        ["ip", "-4", "addr", "show", "dev", "wlan0"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    if "inet " in address.stdout:
        return
    if DHCP_PID.exists():
        pid = int(DHCP_PID.read_text())
        comm = Path(f"/proc/{pid}/comm")
        try:
            name = comm.read_text().strip()
        except FileNotFoundError:
            name = None
        if name is not None:
            if name != "udhcpc":
                raise RuntimeError("Wi-Fi DHCP PID belongs to a different process")
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            for _ in range(20):
                if not comm.exists():
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("Previous Wi-Fi DHCP client did not exit")
    subprocess.run(
        ["udhcpc", "-i", "wlan0", "-b", "-S", "-p", str(DHCP_PID)],
        stdin=subprocess.DEVNULL,
        timeout=10,
        check=True,
    )


def run(command, settings):
    """Keep display ownership while restarting the receiver around suspend."""
    stopping = False

    def request_stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    sleep_failed = False
    while not stopping:
        with SESSION_LOCK.open("ab") as gate:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL)
            try:
                seen_frame = frame_stamp()
                idle_since = time.monotonic()
                while not stopping:
                    status = process.poll()
                    if status is not None:
                        return status if status >= 0 else 128 - status
                    latest = frame_stamp()
                    if latest != seen_frame:
                        seen_frame = latest
                        idle_since = time.monotonic()
                    if (
                        not sleep_failed
                        and time.monotonic() - idle_since
                        >= settings.sleep_after_seconds
                    ):
                        try:
                            if sleep_allowed(settings):
                                try:
                                    fcntl.flock(gate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                                except BlockingIOError:
                                    pass
                                else:
                                    last_connection = os.fstat(gate.fileno()).st_mtime
                                    if (
                                        time.time() - last_connection
                                        >= SESSION_GRACE_SECONDS
                                    ):
                                        break
                                    fcntl.flock(gate, fcntl.LOCK_UN)
                        except OSError as err:
                            print(
                                f"OpenDisplay cannot check sleep policy: {err}",
                                file=sys.stderr,
                            )
                            sleep_failed = True
                    time.sleep(1)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                        print(
                            "OpenDisplay receiver did not stop cleanly; disabling timed suspend",
                            file=sys.stderr,
                        )
                        sleep_failed = True
            if stopping:
                break
            if sleep_failed:
                continue
            try:
                resumed = suspend(settings, lambda: stopping)
            except (OSError, RuntimeError, ValueError) as err:
                print(f"OpenDisplay timed suspend disabled: {err}", file=sys.stderr)
                sleep_failed = True
                continue
            if resumed:
                try:
                    restore_wifi()
                except (
                    OSError,
                    RuntimeError,
                    ValueError,
                    subprocess.SubprocessError,
                ) as err:
                    print(f"OpenDisplay Wi-Fi recovery failed: {err}", file=sys.stderr)
                    sleep_failed = True
    return 0


if __name__ == "__main__":
    config = load_settings(Path.cwd())
    if config.sleep_after_seconds == 0 or not config.opendisplay:
        os.execvp(sys.argv[1], sys.argv[1:])
    sys.exit(run(sys.argv[1:], config))
