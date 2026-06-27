import threading
import time
import subprocess
import sys
from pathlib import Path
from discord_bot.listener import start_bot

# Config aus export/config.py laden
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "export"))
import config

EXPORT_SCRIPT  = Path(__file__).resolve().parent.parent / "export" / "export_json.py"
ELO_SCRIPT     = Path(__file__).resolve().parent.parent / "export" / "elo_calculator.py"
EXPORT_PYTHON  = Path(__file__).resolve().parent.parent / "export" / "venv" / "bin" / "python3"
EXPORT_INTERVAL = config.EXPORT_INTERVAL


def run_script(script_path):
    try:
        result = subprocess.run(
            [str(EXPORT_PYTHON), str(script_path)],
            capture_output=True, text=True
        )
        if result.stdout:
            print(result.stdout.strip())
        if result.returncode != 0 and result.stderr:
            print(f"[{script_path.name} Fehler]", result.stderr.strip())
    except Exception as e:
        print(f"[{script_path.name} Fehler] {e}")


def run_export_loop():
    """Läuft als Background-Thread: exportiert und pusht jede Minute."""
    while True:
        run_script(EXPORT_SCRIPT)
        run_script(ELO_SCRIPT)
        time.sleep(EXPORT_INTERVAL)


if __name__ == "__main__":
    # Export-Loop als Daemon-Thread starten (endet automatisch wenn Bot stoppt)
    t = threading.Thread(target=run_export_loop, daemon=True)
    t.start()
    print("Auto-Export gestartet (alle 60s)")

    start_bot()