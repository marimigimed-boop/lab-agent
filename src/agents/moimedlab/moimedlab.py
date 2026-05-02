"""
moimedlab — агент интерпретации лабораторных анализов
Читает письма из папки "лаборатория диалаб" на moimed23@mail.ru,
интерпретирует анализы через Claude API и сохраняет результат
напрямую в папку "Результаты ЛАБ".
"""

import email
import email.header
import email.utils
import logging
import sys
from datetime import datetime
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path

import anthropic
import pdfplumber
from dotenv import load_dotenv
from imapclient import IMAPClient
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


# ── Извлечение содержимого ─────────────────────────────────────────────────────

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
                    log.info("    PDF: %s", filename)
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
                    raw = payload.decode(charset, errors="replace")
                    plain = re.sub(r"<[^>]+>", " ", raw)
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
            result += str(part)
    return result.strip() or "Пациент (имя не указано)"


def build_full_content(body: str, attachments: list[str]) -> str:
    parts = []
    if body:
        parts.append(f"ТЕКСТ ПИСЬМА:\n{body}")
    for i, att in enumerate(attachments, 1):
        parts.append(f"\nВЛОЖЕНИЕ #{i}:\n{att}")
    return "\n\n".join(parts) if parts else "[Письмо пустое, вложения отсутствуют]"


# ── Промпты ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Ты — медицинский ИИ-ассистент клиники МОЙ МЕД / ЛайтМед.
Врач получающий отчёт: педиатр, терапевт, аллерголог, реабилитолог.

Тебе передаются результаты лабораторных анализов пациента.
Твоя задача:
1. Определить отклонения от нормы (с учётом возраста и пола пациента, если указаны)
2. Оценить степень отклонения: норма / лёгкое / умеренное / выраженное
3. Указать возможные клинические интерпретации
4. Дать рекомендации: повторная сдача, консультация специалиста, коррекция лечения
5. Выделить критические значения, требующие срочного реагирования (отметить ⚠️ СРОЧНО)

Язык ответа: русский. Формат: структурированный, для врача.
Не ставить диагнозы — только интерпретация лабораторных данных.
Если данные нечёткие или нечитаемые — укажи это явно."""


# ── Интерпретация через Claude ─────────────────────────────────────────────────

def interpret_with_claude(patient_name: str, source_email: str, email_date: str, content: str) -> str:
    user_msg = (
        f"Пациент: {patient_name}\n"
        f"Письмо от: {source_email}\n"
        f"Дата письма: {email_date}\n\n"
        f"СОДЕРЖИМОЕ ПИСЬМА И ВЛОЖЕНИЙ:\n{content}\n\n"
        f"Проведи интерпретацию всех лабораторных показателей из этих данных."
    )
    log.info("  Claude: %s", patient_name)
    response = claude.messages.create(
        model="claude-opus-4-7",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text


# ── Форматирование ─────────────────────────────────────────────────────────────

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


def build_raw_message(subject: str, body: str) -> bytes:
    msg = EmailMessage()
    msg["From"]    = MAILRU_EMAIL
    msg["To"]      = MAILRU_EMAIL
    msg["Subject"] = subject
    msg["Date"]    = email.utils.formatdate()
    msg.set_content(body, charset="utf-8")
    return msg.as_bytes()


# ── Основная логика ────────────────────────────────────────────────────────────

def run() -> None:
    log.info("=== moimedlab запущен ===")
    processed = 0
    errors    = 0

    with IMAPClient(IMAP_HOST, port=IMAP_PORT, ssl=True) as client:
        client.login(MAILRU_EMAIL, MAILRU_PASSWORD)
        log.info("Авторизация успешна")

        # Создаём папку результатов если не существует
        if not client.folder_exists(RESULT_FOLDER):
            client.create_folder(RESULT_FOLDER)
            log.info("Папка '%s' создана", RESULT_FOLDER)

        # Выбираем папку с анализами
        try:
            client.select_folder(MAILRU_FOLDER)
        except Exception:
            log.error("Папка '%s' не найдена. Проверьте MAILRU_FOLDER в .env", MAILRU_FOLDER)
            return

        # Ищем непрочитанные письма начиная с SINCE_DATE
        messages = client.search(["UNSEEN", "SINCE", SINCE_DATE])
        if not messages:
            log.info("Непрочитанных писем с %s нет — выходим.", SINCE_DATE)
            return

        log.info("Найдено писем: %d", len(messages))

        for msg_id in messages:
            try:
                log.info("Обрабатываю письмо #%s …", msg_id)

                raw_data  = client.fetch([msg_id], ["RFC822"])
                raw_email = raw_data[msg_id][b"RFC822"]
                msg = email.message_from_bytes(raw_email)

                from_addr = msg.get("From", "неизвестно")
                date_raw  = msg.get("Date", "")
                try:
                    from email.utils import parsedate_to_datetime
                    email_date = parsedate_to_datetime(date_raw).strftime("%d.%m.%Y")
                except Exception:
                    email_date = date_raw or "дата неизвестна"

                body, attachments = extract_email_content(msg)
                patient_name = decode_subject(msg)
                full_content = build_full_content(body, attachments)

                log.info("  %s | %s | %s", patient_name, from_addr, email_date)

                if full_content == "[Письмо пустое, вложения отсутствуют]":
                    log.warning("  Пустое — пропускаю")
                    continue

                interpretation = interpret_with_claude(patient_name, from_addr, email_date, full_content)

                reply_subject = f"Интерпретация анализов — {patient_name} {email_date}"
                reply_raw     = build_raw_message(reply_subject, format_reply(patient_name, email_date, interpretation))

                # Сохраняем напрямую в папку "Результаты ЛАБ"
                client.append(RESULT_FOLDER, reply_raw, flags=["\\Seen"])
                log.info("  Сохранено в '%s'", RESULT_FOLDER)

                # Помечаем исходное письмо как прочитанное
                client.set_flags([msg_id], ["\\Seen"])
                processed += 1

            except Exception as e:
                log.exception("Ошибка #%s: %s", msg_id, e)
                errors += 1

    log.info("=== Готово: обработано %d, ошибок %d ===", processed, errors)


if __name__ == "__main__":
    run()
