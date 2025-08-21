@'
import os, sys
from pathlib import Path
print(">>> HOTFIX SANITY: running")
Path("debug").mkdir(exist_ok=True)
Path("debug/marker.txt").write_text("ran\n", encoding="utf-8")
'@ | Set-Content -Encoding UTF8 .\sidearm_hotfix.py
