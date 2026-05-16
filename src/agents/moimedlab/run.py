"""Точка запуска агента — можно запускать напрямую или через Task Scheduler."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.agents.moimedlab.moimedlab import run

if __name__ == "__main__":
    run()
