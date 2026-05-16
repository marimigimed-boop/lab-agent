"""
Лаб-агент — единая точка запуска.

Использование:
    py lab.py moimed  Иванов        — ищет "Иванов" в МОЙ МЕД  → папка rezalt LAB moimed
    py lab.py litemed Петрова       — ищет "Петрова" в ЛайтМед  → папка litemed LAB rezalt
    py lab.py moimed  "Семья Иглина" — поддерживаются пробелы в фамилии

Результат: Word-файл с шапкой клиники приходит на marimigi@mail.ru в нужную папку.
"""

import sys
import io
from pathlib import Path

# Кириллица в Windows-терминале
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def usage():
    print(__doc__)
    sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        clinic  = sys.argv[1].lower().strip()
        patient = " ".join(sys.argv[2:]).strip()
    else:
        print("-" * 50)
        print("  Лаб-агент - интерпретация анализов")
        print("-" * 50)
        clinic  = input("Клиника (moimed / litemed): ").strip().lower()
        patient = input("Фамилия пациента: ").strip()
        print()

    if clinic in ("moimed", "моймед", "мой мед"):
        from src.agents.moimedlab.find_patient import find_and_send
        find_and_send(patient)

    elif clinic in ("litemed", "лайтмед", "лайт мед"):
        from src.agents.litemedlab.find_patient import find_and_send
        find_and_send(patient)

    else:
        print(f"Неизвестная клиника: '{clinic}'. Укажите moimed или litemed.")
        usage()
