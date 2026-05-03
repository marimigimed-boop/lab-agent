"""
Скрипт: интерпретация анализов семьи Ильягуев/Ильгуев
Читает PDF из ЛАБОРАТОРИЯ ДИАЛАБ, интерпретирует через Claude,
сохраняет в Word и отправляет на marimigi@mail.ru
"""
import email
import email.header
import email.utils
import io
import logging
import os
import smtplib
import sys
from datetime import datetime
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path

import anthropic
import pdfplumber
from dotenv import load_dotenv
from imapclient import IMAPClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.utils.word_builder import build_multi_patient_word_bytes

# ── Настройки ──────────────────────────────────────────────────────────────────
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(env_path)

MAILRU_EMAIL    = os.environ["MAILRU_EMAIL"]       # moimed23@mail.ru
MAILRU_PASSWORD = os.environ["MAILRU_PASSWORD"]
ANTHROPIC_KEY   = os.environ["ANTHROPIC_API_KEY"]
DEST_EMAIL      = os.environ["DEST_EMAIL"]          # marimigi@mail.ru
DEST_PASSWORD   = os.environ["DEST_PASSWORD"]

SOURCE_FOLDER   = "ЛАБОРАТОРИЯ ДИАЛАБ"
IMAP_HOST       = "imap.mail.ru"
SMTP_HOST       = "smtp.mail.ru"
SMTP_PORT       = 465

OUTPUT_FILE     = Path(__file__).parent / "Ильягуев_интерпретация.docx"

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("ilyaguev")

claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# ── Имена пациентов ────────────────────────────────────────────────────────────
SEARCH_NAMES = ["Ильягуев", "Ильягуева", "Ильгуев"]

# ── PDF ────────────────────────────────────────────────────────────────────────
def extract_pdf_text(pdf_bytes: bytes) -> str:
    parts = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                parts.append(t)
    return "\n".join(parts) if parts else "[PDF без текста]"


def decode_header_str(raw) -> str:
    if not raw:
        return ""
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", errors="replace")
    parts = email.header.decode_header(raw)
    result = ""
    for p, enc in parts:
        if isinstance(p, bytes):
            result += p.decode(enc or "utf-8", errors="replace")
        else:
            result += p
    return result


def is_pdf_part(ctype: str, fname: str) -> bool:
    return (ctype in ("application/pdf", "application/x-any", "application/octet-stream")
            and fname.lower().endswith(".pdf")) or ctype == "application/pdf"


def extract_pdfs_from_msg(raw_bytes: bytes) -> list[str]:
    msg = email.message_from_bytes(raw_bytes)
    texts = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdisp = str(part.get("Content-Disposition", ""))
            if "attachment" in cdisp or "inline" in cdisp:
                fname = decode_header_str(part.get_filename() or "")
                payload = part.get_payload(decode=True)
                if payload and is_pdf_part(ctype, fname):
                    log.info("    PDF: %s (%d KB)", fname[:60], len(payload) // 1024)
                    texts.append(f"[ФАЙЛ: {fname}]\n{extract_pdf_text(payload)}")
    return texts


# ── Claude ─────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Ты — медицинский ИИ-ассистент клиники МОЙ МЕД (Московская область).
Врач-получатель: педиатр, терапевт, аллерголог, реабилитолог.
Референсные значения: актуальные нормы 2024–2026 гг. (CLSI, IFCC, приказ МЗ РФ).

ЗАДАЧА: Для каждого показателя:
1. Сравни с референсом (учитывая возраст, пол, единицы из бланка)
2. Статус: ✅ норма | ↑ повышен | ↓ снижен | ⚠️ КРИТИЧНО
3. Степень отклонения: лёгкое (<25%) / умеренное (25–50%) / выраженное (>50%)
4. Краткая клиническая интерпретация
5. Рекомендация: наблюдение / повтор через [срок] / консультация [специалист] / срочная коррекция

В конце — КЛИНИЧЕСКИЙ РЕЗЮМЕ (5–8 предложений): основные отклонения,
возможные причины, приоритетные действия для врача.

ФОРМАТ ВЫВОДА:
## [Название раздела анализа]
| Показатель | Результат | Референс | Статус | Интерпретация |
|---|---|---|---|---|
...
**Рекомендации:** ...

## КЛИНИЧЕСКИЙ РЕЗЮМЕ
[текст]
"""

def interpret_patient(patient_name: str, order_no: str, all_texts: list[str]) -> str:
    combined = "\n\n---\n\n".join(all_texts)
    user_msg = f"""Пациент: {patient_name}
Заявка: {order_no}
Дата интерпретации: {datetime.now().strftime('%d.%m.%Y')}

РЕЗУЛЬТАТЫ АНАЛИЗОВ (все файлы по данной заявке):

{combined}
"""
    log.info("  Claude API: интерпретация %s / %s ...", patient_name, order_no)
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text


# ── Word + SMTP ────────────────────────────────────────────────────────────────
def build_and_send_word(patients_data: list[dict]) -> Path:
    # Формируем список для word_builder
    patients_for_builder = [
        {
            "name":           p["name"],
            "date":           p["date"],
            "order":          p["order"],
            "analysis_count": 1,
            "interpretation": p["interpretation"],
        }
        for p in patients_data
    ]

    docx_bytes = build_multi_patient_word_bytes(
        patients=patients_for_builder,
        title="ИНТЕРПРЕТАЦИЯ ЛАБОРАТОРНЫХ АНАЛИЗОВ — семья Ильягуев",
    )

    # Сохраняем локально
    OUTPUT_FILE.write_bytes(docx_bytes)
    log.info("Word сохранён: %s", OUTPUT_FILE)

    # Отправляем по SMTP
    filename = OUTPUT_FILE.name
    msg = EmailMessage()
    msg["Subject"] = f"Интерпретация анализов — семья Ильягуев — {datetime.now().strftime('%d.%m.%Y')}"
    msg["From"]    = MAILRU_EMAIL
    msg["To"]      = DEST_EMAIL
    msg.set_content(
        "Здравствуйте!\n\n"
        "Во вложении — интерпретация лабораторных анализов семьи Ильягуев.\n"
        "Документ подготовлен автоматически ИИ-ассистентом клиники МОЙ МЕД.\n\n"
        "С уважением,\nМОЙ МЕД"
    )
    msg.add_attachment(
        docx_bytes,
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(MAILRU_EMAIL, MAILRU_PASSWORD)
        smtp.send_message(msg)
    log.info("Письмо отправлено на %s", DEST_EMAIL)
    return OUTPUT_FILE


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    log.info("Подключение к %s ...", IMAP_HOST)
    with IMAPClient(IMAP_HOST, port=993, ssl=True) as client:
        client.login(MAILRU_EMAIL, MAILRU_PASSWORD)
        client.select_folder(SOURCE_FOLDER, readonly=True)

        # Найти все письма для семьи
        all_uids: set[int] = set()
        for name in SEARCH_NAMES:
            found = client.search(["SUBJECT", name], charset="UTF-8")
            all_uids.update(found)
        uids = sorted(all_uids)
        log.info("Найдено писем: %d", len(uids))

        # Получить темы и сгруппировать по (имя пациента, номер заявки)
        envelope_data = client.fetch(uids, ["ENVELOPE"])

        groups: dict[tuple[str, str], list[int]] = {}
        uid_to_meta: dict[int, tuple[str, str, str]] = {}  # uid -> (name, order, date)

        import re
        pat = re.compile(r"для\s+(.+?)\s+по заявке\s+№(\d+)", re.IGNORECASE)

        for uid in uids:
            env = envelope_data[uid][b"ENVELOPE"]
            subj = decode_header_str(env.subject)
            m = pat.search(subj)
            if m:
                name  = m.group(1).strip()
                order = m.group(2).strip()
                date_str = env.date.strftime("%d.%m.%Y") if env.date else "?"
                uid_to_meta[uid] = (name, order, date_str)
                key = (name, order)
                groups.setdefault(key, []).append(uid)

        log.info("Групп (пациент/заявка): %d", len(groups))
        for (name, order), guids in sorted(groups.items()):
            log.info("  %s  (заявка %s): %d писем", name, order, len(guids))

    # Скачать PDF тексты — одно постоянное соединение с NOOP между fetches
    def connect_imap() -> IMAPClient:
        import time
        for attempt in range(5):
            try:
                c = IMAPClient(IMAP_HOST, port=993, ssl=True)
                c.login(MAILRU_EMAIL, MAILRU_PASSWORD)
                c.select_folder(SOURCE_FOLDER, readonly=True)
                return c
            except Exception as e:
                log.warning("Попытка подключения %d/5 не удалась: %s", attempt + 1, e)
                time.sleep(5 * (attempt + 1))
        raise RuntimeError("Не удалось подключиться к IMAP")

    import time

    all_uids_ordered = []
    uid_to_group: dict[int, tuple[str, str]] = {}
    for (name, order), guids in sorted(groups.items()):
        for uid in sorted(guids):
            all_uids_ordered.append(uid)
            uid_to_group[uid] = (name, order)

    # Скачать все PDF в памяти — одно соединение, NOOP каждые 5 писем
    uid_to_texts: dict[int, list[str]] = {}
    client_dl = connect_imap()
    try:
        for i, uid in enumerate(all_uids_ordered):
            subj = decode_header_str(envelope_data[uid][b"ENVELOPE"].subject)
            panel = re.search(r"\((.+?)\)\s*$", subj)
            panel_name = panel.group(1) if panel else "Анализ"
            log.info("  [%d/%d] UID %d: %s", i + 1, len(all_uids_ordered), uid, panel_name)

            for attempt in range(3):
                try:
                    raw_data = client_dl.fetch([uid], ["RFC822"])
                    raw_bytes = raw_data[uid][b"RFC822"]
                    break
                except Exception as e:
                    log.warning("    Fetch UID %d ошибка (попытка %d): %s", uid, attempt + 1, e)
                    time.sleep(3)
                    try:
                        client_dl.logout()
                    except Exception:
                        pass
                    time.sleep(3)
                    client_dl = connect_imap()
            else:
                log.warning("    Пропускаем UID %d", uid)
                uid_to_texts[uid] = []
                continue

            texts = extract_pdfs_from_msg(raw_bytes)
            uid_to_texts[uid] = [f"=== {panel_name} ===\n{t}" for t in texts]

            # NOOP каждые 5 писем для поддержания соединения
            if (i + 1) % 5 == 0:
                try:
                    client_dl.noop()
                except Exception:
                    client_dl = connect_imap()
    finally:
        try:
            client_dl.logout()
        except Exception:
            pass

    patients_data = []
    for (name, order), guids in sorted(groups.items(), key=lambda x: x[0][0]):
        date_str = uid_to_meta[guids[0]][2]
        all_texts = []
        for uid in sorted(guids):
            all_texts.extend(uid_to_texts.get(uid, []))

        if not all_texts:
            log.warning("  Нет PDF для %s / %s — пропускаем", name, order)
            continue

        log.info("Интерпретация: %s / заявка %s (%d секций)", name, order, len(all_texts))
        interpretation = interpret_patient(name, order, all_texts)
        patients_data.append({
            "name": name,
            "order": order,
            "date": date_str,
            "interpretation": interpretation,
        })

    if not patients_data:
        log.error("Нет данных для документа!")
        return

    log.info("Создание Word документа и отправка на %s ...", DEST_EMAIL)
    build_and_send_word(patients_data)

    log.info("Готово!")


if __name__ == "__main__":
    main()
