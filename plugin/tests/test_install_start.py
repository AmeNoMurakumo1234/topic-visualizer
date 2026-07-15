import json, subprocess, sys
from pathlib import Path

INSTALLER = Path(__file__).resolve().parent.parent / "server" / "install_service.py"

def test_dry_run_reports_started_key_and_starts_nothing():
    out = subprocess.run([sys.executable, str(INSTALLER), "--dry-run"],
                         capture_output=True, text=True)
    line = [l for l in out.stdout.splitlines() if l.strip().startswith("{")][-1]
    data = json.loads(line)
    assert "started" in data            # the JSON contract now carries it
    assert data["started"] is False     # dry-run must never launch a process
