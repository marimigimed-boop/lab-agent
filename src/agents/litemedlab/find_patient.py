"""
Поиск писем конкретного пациента в папке ЛайтМед,
интерпретация через Claude и отправка Word-документом на marimigi@mail.ru.
Запуск: python find_patient.py "Фамилия"
"""

import email
import email.header
import email.utils
import sys
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
from imapclient import IMAPClient
import os

load_dotenv(_ROOT / ".env")

MAILRU_EMAIL    = os.environ["LITEMED_EMAIL"]
MAILRU_PASSWORD = os.environ["LITEMED_PASSWORD"]
MAILRU_FOLDER   = os.getenv("LITEMED_FOLDER", "ДИАЛАБ  ЛАБОРАТОРИЯ_РЕЗУЛЬТАТЫ")
DEST_EMAIL      = os.getenv("DEST_EMAIL", "marimigi@mail.ru")
DEST_PASSWORD   = os.environ["DEST_PASSWORD"]
DEST_FOLDER     = os.getenv("LITEMED_DEST_FOLDER", "litemed LAB rezalt")

IMAP_HOST = "imap.mail.ru"
IMAP_PORT = 993

from src.utils.word_builder import build_multi_patient_word_bytes
from src.agents.litemedlab.litemedlab import (
    extract_email_content, decode_subject, build_full_content,
    interpret_with_claude,
)


def decode_header_str(raw: str) -> str:
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    return "".join(
        p.decode(e or "utf-8", errors="replace") if isinstance(p, bytes) else p
        for p, e in parts
    )


def save_doc_to_dest_folder(subject: str, patient_query: str,
                             docx_bytes: bytes, filename: str) -> None:
    import email as _email_lib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"]    = MAILRU_EMAIL
    msg["To"]      = DEST_EMAIL
    msg["Subject"] = subject
    msg["Date"]    = _email_lib.utils.formatdate()
    msg.set_content(
        f"Пациент: {patient_query}\n"
        f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        "Результаты во вложении (.docx).\n\nКлиника ЛАЙТМЕД",
        charset="utf-8",
    )
    msg.add_attachment(
        docx_bytes,
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )
    with IMAPClient(IMAP_HOST, port=IMAP_PORT, ssl=True) as dest:
        dest.login(DEST_EMAIL, DEST_PASSWORD)
        if not dest.folder_exists(DEST_FOLDER):
            dest.create_folder(DEST_FOLDER)
        dest.append(DEST_FOLDER, msg.as_bytes(), flags=["\\Seen"])
    print(f"  Сохранено в '{DEST_FOLDER}' на {DEST_EMAIL}")


def find_and_send(patient_name_fragment: str) -> None:
    print(f"[ЛайтМед] Ищу '{patient_name_fragment}' в папке '{MAILRU_FOLDER}'...")

    with IMAPClient(IMAP_HOST, port=IMAP_PORT, ssl=True) as client:
        client.login(MAILRU_EMAIL, MAILRU_PASSWORD)
        print("Авторизация успешна")

        client.select_folder(MAILRU_FOLDER)
        all_messages = client.search(["ALL"])
        print(f"Всего писем в папке: {len(all_messages)}")

        found = []
        for msg_id in all_messages:
            raw_data    = client.fetch([msg_id], ["ENVELOPE"])
            envelope    = raw_data[msg_id][b"ENVELOPE"]
            subject_raw = envelope.subject or b""
            subject = decode_header_str(
                subject_raw.decode("utf-8", errors="replace")
                if isinstance(subject_raw, bytes) else str(subject_raw)
            )
            if patient_name_fragment.lower() in subject.lower():
                found.append(msg_id)
                print(f"  Найдено: #{msg_id} | {subject}")

        if not found:
            print(f"Писем с '{patient_name_fragment}' не найдено.")
            return

        print(f"\nНайдено {len(found)} писем. Интерпретирую...")
        results = []

        for msg_id in found:
            raw_data  = client.fetch([msg_id], ["RFC822"])
            raw_email = raw_data[msg_id][b"RFC822"]
            msg = email.message_from_bytes(raw_email)

            from_addr = msg.get("From", "неизвестно")
            date_raw  = msg.get("Date", "")
            try:
                email_date = parsedate_to_datetime(date_raw).strftime("%d.%m.%Y")
            except Exception:
                email_date = date_raw or "дата неизвестна"

            body, attachments = extract_email_content(msg)
            patient_name = decode_subject(msg)
            full_content = build_full_content(body, attachments)

            print(f"  Обрабатываю: {patient_name} | {email_date}")

            if full_content == "[Письмо пустое, вложения отсутствуют]":
                print("  Пустое — пропускаю")
                continue

            interpretation = interpret_with_claude(
                patient_name, from_addr, email_date, full_content
            )
            results.append({
                "name": patient_name,
                "date": email_date,
                "order": "",
                "analysis_count": 1,
                "interpretation": interpretation,
            })
            print(f"\n{'=' * 60}")
            print(f"  {patient_name}  |  {email_date}")
            print(f"{'=' * 60}")
            print(interpretation)
            print(f"{'=' * 60}\n")

    if not results:
        print("Нет результатов для отправки.")
        return

    print(f"\nФормирую Word-документ ({len(results)} интерпретаций)...")
    docx_bytes = build_multi_patient_word_bytes(
        patients=results,
        title=f"ИНТЕРПРЕТАЦИЯ ЛАБОРАТОРНЫХ АНАЛИЗОВ — {patient_name_fragment.upper()}",
    )

    ts       = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"Интерпретация_{patient_name_fragment}_{ts}.docx"
    subject  = (
        f"[ЛайтМед] Интерпретация анализов — {patient_name_fragment} "
        f"({len(results)} анализ{'а' if 2 <= len(results) <= 4 else 'ов'})"
    )

    save_doc_to_dest_folder(subject, patient_name_fragment, docx_bytes, filename)
    print(f"\nГотово. Word-файл '{filename}' отправлен в '{DEST_FOLDER}' на {DEST_EMAIL}")


if __name__ == "__main__":
    patient = sys.argv[1] if len(sys.argv) > 1 else ""
    if not patient:
        print("Укажите фамилию пациента: python find_patient.py \"Мазур\"")
        sys.exit(1)
    find_and_send(patient)
