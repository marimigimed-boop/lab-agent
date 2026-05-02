"""
moimedlab — агент интерпретации лабораторных анализов
Читает письма из папки "лаборатория диалаб" на moimed23@mail.ru,
интерпретирует анализы через Claude API и сохраняет результат
напрямую в папку "Результаты ЛАБ" через IMAP.
"""

import email
import email.header
import imaplib
import logging
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
env_path = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(env_path)

MAILRU_EMAIL    = os.environ["MAILRU_EMAIL"]
MAILRU_PASSWORD = os.environ["MAILRU_PASSWORD"]
ANTHROPIC_KEY   = os.environ["ANTHROPIC_API_KEY"]
MAILRU_FOLDER   = os.getenv("MAILRU_FOLDER", "лаборатория диалаб")
RESULT_FOLDER   = os.getenv("RESULT_FOLDER", "Результаты ЛАБ")
SINCE_DATE      = os.getenv("SINCE_DATE", "01-May-2025")

IMAP_HOST = "imap.mail.ru"
IMAP_PORT = 993

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
    text_parts: list[str] = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts) if text_parts else "[PDF не содержит текста]"


def extract_email_content(msg: email.message.Message) -> tuple[str, list[str]]:
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
                    attachment_texts.append(f"[ВЛОЖЕНИЕ: {filename}]\n{extract_pdf_text(payload)}")
                elif content_type.startswith("text/"):
                    charset = part.get_content_charset("utf-8")
                    attachment_texts.append(payload.decode(charset, errors="replace"))
            elif content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset("utf-8")
                    body_parts.append(payload.decode(charset, errors="replace"))
            elif content_type == "text/html" and not body_parts:
                payload = part.get_payload(decode=True)
                if payload:
                    import re
                    charset = part.get_content_charset("utf-8")
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


def decode_subject(msg: email.message.Message) -> str:
    subject = msg.get("Subject", "") or ""
    decoded_parts = email.header.decode_header(subject)
    result = ""
    for part, enc in decoded_parts:
        if isinstance(part, bytes):
            result += part.decode(enc or "utf-8", errors="replace")
        else:
            result += part
    return result.strip() or "Пациент (имя не указано)"


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


# ── Форматирование письма-результата ──────────────────────────────────────────

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
    )


# ── Сохранение в папку через IMAP APPEND ──────────────────────────────────────

def ensure_folder_exists(imap: imaplib.IMAP4_SSL, folder: str) -> None:
    """Создаёт папку если она не существует."""
    status, folders = imap.list()
    existing = [f.decode() if isinstance(f, bytes) else f for f in (folders or [])]
    folder_exists = any(f'"{folder}"' in line or f' {folder}' in line for line in existing)
    if not folder_exists:
        imap.create(f'"{folder}"')
        log.info("Папка '%s' создана", folder)


def save_to_folder(imap: imaplib.IMAP4_SSL, subject: str, body: str) -> None:
    """Сохраняет письмо напрямую в папку RESULT_FOLDER через IMAP APPEND."""
    msg = EmailMessage()
    msg["From"]    = MAILRU_EMAIL
    msg["To"]      = MAILRU_EMAIL
    msg["Subject"] = subject
    msg["Date"]    = email.utils.formatdate()
    msg.set_content(body, charset="utf-8")

    raw = msg.as_bytes()
    imap.append(f'"{RESULT_FOLDER}"', "\\Seen", imaplib.Time2Internaldate(datetime.now()), raw)
    log.info("  Сохранено в папку '%s': %s", RESULT_FOLDER, subject)


# ── Основная логика ────────────────────────────────────────────────────────────

def run() -> None:
    log.info("=== moimedlab запущен ===")
    processed = 0
    errors    = 0

    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as imap:
        imap.login(MAILRU_EMAIL, MAILRU_PASSWORD)
        log.info("Авторизация успешна")

        # Убеждаемся что папка результатов существует
        ensure_folder_exists(imap, RESULT_FOLDER)

        # Выбираем папку с анализами
        status, _ = imap.select(f'"{MAILRU_FOLDER}"')
        if status != "OK":
            log.error("Папка '%s' не найдена. Проверьте MAILRU_FOLDER в .env", MAILRU_FOLDER)
            return

        # Ищем непрочитанные письма начиная с SINCE_DATE
        search_criteria = f'(UNSEEN SINCE {SINCE_DATE})'
        log.info("Критерий поиска: %s", search_criteria)
        status, data = imap.search(None, search_criteria)
        if status != "OK" or not data[0]:
            log.info("Непрочитанных писем с %s нет — выходим.", SINCE_DATE)
            return

        msg_ids = data[0].split()
        log.info("Найдено писем: %d", len(msg_ids))

        for msg_id in msg_ids:
            try:
                log.info("Обрабатываю письмо #%s …", msg_id.decode())

                _, raw_data = imap.fetch(msg_id, "(RFC822)")
                raw_email = raw_data[0][1]
                msg = email.message_from_bytes(raw_email, policy=policy.default)

                from_addr  = msg.get("From", "неизвестно")
                date_raw   = msg.get("Date", "")
                try:
                    email_date = parsedate_to_datetime(date_raw).strftime("%d.%m.%Y")
                except Exception:
                    email_date = date_raw or "дата неизвестна"

                body, attachments = extract_email_content(msg)
                patient_name = decode_subject(msg)
                full_content = build_full_content(body, attachments)

                log.info("  Пациент: %s | От: %s | Дата: %s", patient_name, from_addr, email_date)

                if full_content == "[Письмо пустое, вложения отсутствуют]":
                    log.warning("  Письмо пустое — пропускаю")
                    continue

                interpretation = interpret_with_claude(patient_name, from_addr, email_date, full_content)

                reply_body    = format_reply(patient_name, email_date, interpretation)
                reply_subject = f"Интерпретация анализов — {patient_name} {email_date}"
                save_to_folder(imap, reply_subject, reply_body)

                # Помечаем исходное письмо как прочитанное
                imap.store(msg_id, "+FLAGS", "\\Seen")
                processed += 1

            except Exception as e:
                log.exception("Ошибка при обработке письма #%s: %s", msg_id.decode(), e)
                errors += 1

    log.info("=== Готово: обработано %d, ошибок %d ===", processed, errors)


if __name__ == "__main__":
    run()
