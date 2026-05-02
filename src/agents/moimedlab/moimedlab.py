"""
moimedlab — агент интерпретации лабораторных анализов
Читает письма из папки dialab на moimed23@mail.ru,
интерпретирует анализы через Claude API и отправляет ответ.
"""

import email
import imaplib
import logging
import smtplib
import sys
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from io import BytesIO
from pathlib import Path

import anthropic
import pdfplumber
from dotenv import load_dotenv
import os

# ── Загрузка настроек ──────────────────────────────────────────────────────────
# Ищем .env в корне проекта (3 уровня вверх от этого файла)
env_path = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(env_path)

MAILRU_EMAIL    = os.environ["MAILRU_EMAIL"]
MAILRU_PASSWORD = os.environ["MAILRU_PASSWORD"]
ANTHROPIC_KEY   = os.environ["ANTHROPIC_API_KEY"]
MAILRU_FOLDER   = os.getenv("MAILRU_FOLDER", "dialab")
SEND_TO         = os.getenv("SEND_TO", MAILRU_EMAIL)

IMAP_HOST = "imap.mail.ru"
IMAP_PORT = 993
SMTP_HOST = "smtp.mail.ru"
SMTP_PORT = 465

# ── Логирование ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "moimedlab.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("moimedlab")

# ── Claude client ──────────────────────────────────────────────────────────────
claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)


# ── Вспомогательные функции ────────────────────────────────────────────────────

def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Извлекает текст из PDF-вложения."""
    text_parts: list[str] = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts) if text_parts else "[PDF не содержит текста]"


def extract_email_content(msg: email.message.Message) -> tuple[str, list[str]]:
    """
    Возвращает (text_body, list_of_attachment_texts).
    Обрабатывает multipart письма, извлекает PDF и текстовые вложения.
    """
    body_parts: list[str] = []
    attachment_texts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disp  = str(part.get("Content-Disposition", ""))

            if "attachment" in content_disp or "inline" in content_disp:
                filename = part.get_filename() or ""
                payload  = part.get_payload(decode=True)
                if not payload:
                    continue

                if filename.lower().endswith(".pdf") or content_type == "application/pdf":
                    log.info("    Извлекаю PDF: %s", filename)
                    pdf_text = extract_pdf_text(payload)
                    attachment_texts.append(f"[ВЛОЖЕНИЕ: {filename}]\n{pdf_text}")
                elif content_type.startswith("text/"):
                    charset = part.get_content_charset("utf-8")
                    attachment_texts.append(payload.decode(charset, errors="replace"))
            elif content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset("utf-8")
                    body_parts.append(payload.decode(charset, errors="replace"))
            elif content_type == "text/html" and not body_parts:
                # HTML fallback — берём только если нет plain text
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset("utf-8")
                    # Упрощённое удаление тегов
                    import re
                    raw_html = payload.decode(charset, errors="replace")
                    plain = re.sub(r"<[^>]+>", " ", raw_html)
                    plain = re.sub(r"\s{2,}", " ", plain).strip()
                    body_parts.append(plain)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset("utf-8")
            body_parts.append(payload.decode(charset, errors="replace"))

    return "\n".join(body_parts).strip(), attachment_texts


def guess_patient_name(msg: email.message.Message, body: str) -> str:
    """Пытается вычислить имя пациента из темы письма или тела."""
    subject = msg.get("Subject", "") or ""
    # Декодируем RFC 2047
    decoded_parts = email.header.decode_header(subject)
    decoded_subject = ""
    for part, enc in decoded_parts:
        if isinstance(part, bytes):
            decoded_subject += part.decode(enc or "utf-8", errors="replace")
        else:
            decoded_subject += part
    # Берём тему как имя, если она не пустая
    return decoded_subject.strip() if decoded_subject.strip() else "Пациент (имя не указано)"


def build_full_content(body: str, attachments: list[str]) -> str:
    parts = []
    if body:
        parts.append(f"ТЕКСТ ПИСЬМА:\n{body}")
    for i, att in enumerate(attachments, 1):
        parts.append(f"\nВЛОЖЕНИЕ #{i}:\n{att}")
    return "\n\n".join(parts) if parts else "[Письмо пустое, вложения отсутствуют]"


# ── Интерпретация через Claude ─────────────────────────────────────────────────

def interpret_with_claude(patient_name: str, source_email: str, email_date: str, content: str) -> str:
    from .prompts import SYSTEM_PROMPT, build_user_message

    user_msg = build_user_message(patient_name, source_email, email_date, content)

    log.info("  Отправляю в Claude: %s", patient_name)
    response = claude.messages.create(
        model="claude-opus-4-7",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text


# ── Форматирование ответного письма ───────────────────────────────────────────

def format_reply(patient_name: str, email_date: str, interpretation: str) -> str:
    sep = "━" * 50
    return (
        f"{sep}\n"
        f"ИНТЕРПРЕТАЦИЯ ЛАБОРАТОРНЫХ ПОКАЗАТЕЛЕЙ\n"
        f"{sep}\n"
        f"Пациент:       {patient_name}\n"
        f"Дата анализов: {email_date}\n"
        f"Сформировано:  {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
        f"{sep}\n\n"
        f"{interpretation}\n\n"
        f"{sep}\n"
        f"Сгенерировано агентом moimedlab | МОЙ МЕД\n"
        f"Это автоматическое письмо — не отвечайте на него напрямую.\n"
    )


# ── SMTP — отправка ────────────────────────────────────────────────────────────

def send_reply(subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"]    = MAILRU_EMAIL
    msg["To"]      = SEND_TO
    msg["Subject"] = subject
    msg.set_content(body, charset="utf-8")

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(MAILRU_EMAIL, MAILRU_PASSWORD)
        smtp.send_message(msg)
    log.info("  Ответ отправлен: %s", subject)


# ── Основная логика ────────────────────────────────────────────────────────────

def run() -> None:
    log.info("=== moimedlab запущен ===")
    processed = 0
    errors    = 0

    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as imap:
        imap.login(MAILRU_EMAIL, MAILRU_PASSWORD)
        log.info("Авторизация успешна")

        # Выбираем папку dialab
        status, _ = imap.select(f'"{MAILRU_FOLDER}"')
        if status != "OK":
            log.error("Папка '%s' не найдена. Проверьте MAILRU_FOLDER в .env", MAILRU_FOLDER)
            return

        # Ищем непрочитанные письма
        status, data = imap.search(None, "UNSEEN")
        if status != "OK" or not data[0]:
            log.info("Непрочитанных писем нет — выходим.")
            return

        msg_ids = data[0].split()
        log.info("Найдено непрочитанных писем: %d", len(msg_ids))

        for msg_id in msg_ids:
            try:
                log.info("Обрабатываю письмо #%s …", msg_id.decode())

                # Загружаем письмо целиком
                _, raw_data = imap.fetch(msg_id, "(RFC822)")
                raw_email = raw_data[0][1]
                msg = email.message_from_bytes(raw_email, policy=policy.default)

                # Метаданные
                from_addr  = msg.get("From", "неизвестно")
                date_raw   = msg.get("Date", "")
                try:
                    email_date = parsedate_to_datetime(date_raw).strftime("%d.%m.%Y")
                except Exception:
                    email_date = date_raw or "дата неизвестна"

                # Содержимое
                body, attachments = extract_email_content(msg)
                patient_name = guess_patient_name(msg, body)
                full_content = build_full_content(body, attachments)

                log.info("  Пациент: %s | От: %s | Дата: %s", patient_name, from_addr, email_date)

                if not full_content.strip() or full_content == "[Письмо пустое, вложения отсутствуют]":
                    log.warning("  Письмо пустое — пропускаю")
                    continue

                # Интерпретация
                interpretation = interpret_with_claude(patient_name, from_addr, email_date, full_content)

                # Формируем и отправляем ответ
                reply_body    = format_reply(patient_name, email_date, interpretation)
                reply_subject = f"Интерпретация анализов — {patient_name} {email_date}"
                send_reply(reply_subject, reply_body)

                # Помечаем как прочитанное
                imap.store(msg_id, "+FLAGS", "\\Seen")
                processed += 1

            except Exception as e:
                log.exception("Ошибка при обработке письма #%s: %s", msg_id.decode(), e)
                errors += 1

    log.info("=== Готово: обработано %d, ошибок %d ===", processed, errors)


if __name__ == "__main__":
    run()
