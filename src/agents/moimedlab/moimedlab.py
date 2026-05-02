"""
moimedlab — агент интерпретации лабораторных анализов
Читает письма из папки "лаборатория диалаб" на moimed23@mail.ru,
интерпретирует анализы через Claude API и отправляет результат
на marimigi@mail.ru в папку "rezalt LAB moimed".
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
MAILRU_FOLDER   = os.getenv("MAILRU_FOLDER", "ЛАБОРАТОРИЯ ДИАЛАБ")
SINCE_DATE      = os.getenv("SINCE_DATE", "02-May-2026")
DEST_EMAIL      = os.getenv("DEST_EMAIL", "marimigi@mail.ru")
DEST_PASSWORD   = os.environ["DEST_PASSWORD"]
DEST_FOLDER     = os.getenv("DEST_FOLDER", "rezalt LAB moimed")

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


def decode_filename(raw: str) -> str:
    """Декодирует RFC 2047 имя файла (mail.ru отправляет в base64)."""
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    return "".join(
        p.decode(e or "utf-8", errors="replace") if isinstance(p, bytes) else p
        for p, e in parts
    )


def is_pdf_part(content_type: str, filename: str) -> bool:
    """Диалаб отправляет PDF с content-type application/x-any — проверяем по имени файла."""
    return (
        content_type in ("application/pdf", "application/x-any", "application/octet-stream")
        and filename.lower().endswith(".pdf")
    ) or content_type == "application/pdf"


def extract_email_content(msg: email.message.Message) -> tuple[str, list[str]]:
    body_parts: list[str] = []
    attachment_texts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disp  = str(part.get("Content-Disposition", ""))

            if "attachment" in content_disp or "inline" in content_disp:
                filename = decode_filename(part.get_filename() or "")
                payload  = part.get_payload(decode=True)
                if not payload:
                    continue
                if is_pdf_part(content_type, filename):
                    log.info("    PDF: %s (%d KB)", filename[:50], len(payload) // 1024)
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

SYSTEM_PROMPT = """Ты — медицинский ИИ-ассистент клиники МОЙ МЕД / ЛайтМед (Московская область).
Врач-получатель: педиатр, терапевт, аллерголог, реабилитолог.
Референсные значения: актуальные нормы 2024–2026 гг. (CLSI, IFCC, приказ МЗ РФ).

═══════════════════════════════════════════
ЗАДАЧА
═══════════════════════════════════════════
Для каждого показателя в результатах:
1. Сравнить с референсом (учитывая возраст, пол, единицы измерения из бланка)
2. Статус: ✅ норма | ↑ повышен | ↓ снижен | ⚠️ КРИТИЧНО
3. Степень отклонения: лёгкое (<25% от границы) / умеренное (25–50%) / выраженное (>50%)
4. Краткая клиническая интерпретация
5. Рекомендация: наблюдение / повторный анализ через [срок] / консультация [специалист] / срочная коррекция

═══════════════════════════════════════════
АКТУАЛЬНЫЕ РЕФЕРЕНСЫ 2026 (основные)
═══════════════════════════════════════════

ОБЩИЙ АНАЛИЗ КРОВИ (ОАК):
• Гемоглобин: муж 130–175 г/л, жен 120–160 г/л, дети 0–1 мес 135–200, 1–6 мес 95–140, 6 мес–6 лет 105–140, 6–12 лет 115–150, 12–18 лет муж 130–160 жен 115–150
• Эритроциты: муж 4,2–5,6×10¹²/л, жен 3,8–5,1, дети 0–1 мес 3,9–6,0, 1–12 мес 3,3–5,2
• Гематокрит: муж 40–52%, жен 37–47%
• MCV (средний объём): 80–100 фл (микроцитоз <80, макроцитоз >100)
• MCH: 26–34 пг
• MCHC: 320–380 г/л
• Тромбоциты: 150–400×10⁹/л (⚠️ <50 или >1000 — критично)
• Лейкоциты: взрослые 4,0–9,0×10⁹/л; дети 1–3 года 6,0–17,0; 3–10 лет 6,0–11,5; 10–18 лет 4,5–13,0
• Нейтрофилы: 48–78% (или 1,8–6,5×10⁹/л); ⚠️ нейтропения <1,0×10⁹/л
• Лимфоциты: взрослые 18–40%; дети до 5 лет 40–70%
• Моноциты: 2–11%
• Эозинофилы: 0–5% (>10% — эозинофилия, аллергия/паразиты)
• Базофилы: 0–1%
• СОЭ: муж <15 мм/ч, жен <20 мм/ч, дети <12 мм/ч (по Вестергрену)
• Ретикулоциты: 0,5–1,5%

БИОХИМИЯ КРОВИ:
• Глюкоза натощак: 3,9–5,5 ммоль/л (⚠️ <2,8 или >16,7 — критично); 5,6–6,9 — предиабет; ≥7,0 — диабет
• HbA1c: норма <5,7%; предиабет 5,7–6,4%; диабет ≥6,5%
• Общий белок: 64–84 г/л
• Альбумин: 35–52 г/л (⚠️ <25 — критично)
• АЛТ (АЛАТ): муж <41 Ед/л, жен <31 Ед/л (новые нормы IFCC 2024)
• АСТ (АСАТ): муж <40 Ед/л, жен <32 Ед/л
• ГГТП: муж <60 Ед/л, жен <40 Ед/л
• Щелочная фосфатаза: взрослые 40–130 Ед/л; дети и подростки до 350 Ед/л
• Билирубин общий: 3,4–17,1 мкмоль/л; прямой <4,6; непрямой <12,7
• Мочевина: 2,5–8,3 ммоль/л (⚠️ >25 — критично)
• Креатинин: муж 62–115 мкмоль/л, жен 44–97 мкмоль/л
• СКФ (CKD-EPI 2021): норма >90 мл/мин/1,73м²; 60–90 — умеренное снижение; <60 — ХБП
• Мочевая кислота: муж 208–428 мкмоль/л, жен 155–357 мкмоль/л
• Общий холестерин: <5,0 ммоль/л (оптим.), 5,0–6,2 погранично, >6,2 высокий
• ЛПНП: <3,0 ммоль/л (норма), <1,8 при ССЗ
• ЛПВП: муж >1,0 ммоль/л, жен >1,2 ммоль/л
• Триглицериды: <1,7 ммоль/л (норма), 1,7–5,6 высокие, >5,6 ⚠️ риск панкреатита
• Железо: муж 11,6–30,4 мкмоль/л, жен 8,9–26,8 мкмоль/л
• Ферритин: муж 20–250 мкг/л, жен 10–120 мкг/л (дефицит <12, при анемии хронических болезней может быть ↑)
• ОЖСС: 45–77 мкмоль/л
• Трансферрин: 2,0–3,6 г/л
• Кальций общий: 2,15–2,55 ммоль/л (⚠️ <1,75 или >3,5 — критично)
• Кальций ионизированный: 1,15–1,35 ммоль/л
• Фосфор: взрослые 0,81–1,45 ммоль/л; дети 1,3–2,1
• Магний: 0,70–1,05 ммоль/л
• Натрий: 136–145 ммоль/л (⚠️ <125 или >155 — критично)
• Калий: 3,5–5,1 ммоль/л (⚠️ <2,8 или >6,2 — критично для сердца)
• Хлор: 97–108 ммоль/л
• С-реактивный белок (СРБ): <5 мг/л (высокочувств. CRP <1,0 мг/л для ССЗ-риска)
• Прокальцитонин: <0,1 нг/мл норма; 0,1–0,5 сомнительно; >0,5 бактериальная инфекция; >2,0 ⚠️ сепсис
• Ферритин как маркер воспаления: >500 мкг/л — макрофагальная активация
• Фибриноген: 2,0–4,0 г/л (⚠️ <1,0 — риск кровотечений; >7,0 — гиперкоагуляция)
• D-димер: <0,5 мкг/мл (FEU); повышение — ТЭЛА, ДВС, тромбоз
• МНО (INR): норма 0,85–1,15; при варфарине терапевт. 2,0–3,0
• АЧТВ: 25–37 сек
• ПТВ: 11–15 сек
• Амилаза: 25–125 Ед/л
• Липаза: 13–60 Ед/л (⚠️ >3×норма — острый панкреатит)
• ЛДГ: 125–243 Ед/л
• КФК общая: муж <195 Ед/л, жен <170 Ед/л
• КФК-МВ: <24 Ед/л или <6% от общей КФК
• Тропонин I (высокочувств.): <19 нг/л (мужчины), <16 нг/л (женщины) — нормы 2025

ЩИТОВИДНАЯ ЖЕЛЕЗА:
• ТТГ: 0,4–4,0 мМЕ/л (новая норма ВОЗ 2023); при беременности: I триместр 0,1–2,5; II 0,2–3,0; III 0,3–3,5
• Св. Т4: 9,0–19,1 пмоль/л (или 0,71–1,48 нг/дл)
• Св. Т3: 2,6–5,7 пмоль/л
• Антитела к ТПО (АТ-ТПО): <34 МЕ/мл
• Антитела к ТГ (АТ-ТГ): <115 МЕ/мл

ГОРМОНЫ (общие):
• Кортизол утренний (8:00–10:00): 138–635 нмоль/л
• ДГЭА-С: муж 20–59 лет 88–483 мкг/дл; жен 65–380 мкг/дл
• Инсулин натощак: 2,6–24,9 мкЕд/мл; HOMA-IR <2,7 (≥2,7 — инсулинорезистентность)
• С-пептид: 0,9–7,1 нг/мл
• Пролактин: муж 86–324 мМЕ/л; жен вне беременности 102–496 мМЕ/л
• ФСГ: жен фолл. 3,5–12,5; овул. 4,7–21,5; лют. 1,7–7,7; постменопауза 25–135 МЕ/л
• ЛГ: жен фолл. 2,4–12,6; овул. 14,0–95,6; лют. 1,0–11,4 МЕ/л
• Эстрадиол: жен фолл. 68–1269 пмоль/л; лют. 131–1655; постменопауза <73
• Прогестерон: жен лют. фазы 6,99–56,63 нмоль/л; при беременности значительно выше
• Тестостерон общий: муж 10,4–34,7 нмоль/л; жен 0,52–2,43 нмоль/л
• АМГ (антимюллеров гормон): норма жен 1,0–10,6 нг/мл; снижен <1,0 (сниженный овар. резерв)
• ПТГ (паратгормон): 15–65 пг/мл
• 25-OH витамин D: дефицит <20 нг/мл; недостаточность 20–30; норма 30–100; токсичность >150

АЛЛЕРГОЛОГИЯ (IgE):
• Общий IgE: взрослые <100 МЕ/мл; дети до 1 года <15; 1–5 лет <60; 6–9 лет <90; 10–16 лет <200
• Специфические IgE: класс 0 (<0,35) — нет сенсибилизации; класс 1 (0,35–0,7) — слабая; класс 2 (0,71–3,5) — умеренная; класс 3–6 (>3,5) — выраженная/очень высокая
• Триптаза: <11,4 мкг/л (норма); >20 — мастоцитоз или анафилаксия

МОЧЕВОЙ ОСАДОК (ОАМ):
• Белок: <0,14 г/л (следы допустимо <0,033 г/л)
• Глюкоза: отсутствует
• Лейкоциты: <5 в п/зр (мужчины), <7 (женщины)
• Эритроциты: 0–2 в п/зр
• Цилиндры: единичные гиалиновые допустимы
• Удельный вес: 1,010–1,025

МАРКЕРЫ ПОЧЕК:
• Микроальбумин в моче: <30 мг/г креатинина (норма); 30–300 — микроальбуминурия; >300 — макроальбуминурия
• Суточная протеинурия: <150 мг/сут

ИНФЕКЦИИ / ИММУНОЛОГИЯ:
• СОЭ + CРБ высокочувств. + прокальцитонин — триада маркеров воспаления
• ИЛ-6: <7 пг/мл (норма); >40 — выраженное воспаление; >1000 — цитокиновый шторм
• Ферритин >500 мкг/л + ↑ТГ + цитопения = исключить гемофагоцитарный синдром
• АНА (антинуклеарные АТ): норма отрицательно (титр <1:40)
• АНЦА (антинейтрофильные): отрицательно

═══════════════════════════════════════════
ФОРМАТ ОТВЕТА
═══════════════════════════════════════════

## Пациент: [ФИО] | [возраст] | [пол]
## Тип анализа: [название]
## Дата: [дата]

### ПОКАЗАТЕЛИ:
| Показатель | Результат | Референс | Статус |
|---|---|---|---|
| Гемоглобин | 98 г/л | 120–160 | ↓ умеренно |

### КЛИНИЧЕСКАЯ ИНТЕРПРЕТАЦИЯ:
[Связная интерпретация отклонений, их возможные причины]

### РЕКОМЕНДАЦИИ:
[Конкретные действия — повторный анализ, консультация, лечение]

### ⚠️ КРИТИЧНЫЕ ЗНАЧЕНИЯ (если есть):
[Что требует немедленного реагирования]

---
Правила:
- Не ставить диагнозы — только интерпретация данных
- Учитывать возраст и пол пациента при оценке норм
- Если значение в бланке имеет собственный референс — использовать его
- Если данные нечитаемые или недостаточные — указать явно
- Язык ответа: русский"""


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


def build_raw_message(subject: str, body: str, to: str) -> bytes:
    msg = EmailMessage()
    msg["From"]    = MAILRU_EMAIL
    msg["To"]      = to
    msg["Subject"] = subject
    msg["Date"]    = email.utils.formatdate()
    msg.set_content(body, charset="utf-8")
    return msg.as_bytes()



def save_to_dest_folder(subject: str, body: str) -> None:
    """Сохраняет письмо напрямую в папку DEST_FOLDER на DEST_EMAIL через IMAP."""
    raw = build_raw_message(subject, body, DEST_EMAIL)
    with IMAPClient(IMAP_HOST, port=IMAP_PORT, ssl=True) as dest:
        dest.login(DEST_EMAIL, DEST_PASSWORD)
        if not dest.folder_exists(DEST_FOLDER):
            dest.create_folder(DEST_FOLDER)
            log.info("  Папка '%s' создана на %s", DEST_FOLDER, DEST_EMAIL)
        dest.append(DEST_FOLDER, raw, flags=["\\Seen"])
        log.info("  Сохранено в '%s' на %s", DEST_FOLDER, DEST_EMAIL)


# ── Основная логика ────────────────────────────────────────────────────────────

def run() -> None:
    log.info("=== moimedlab запущен ===")
    processed = 0
    errors    = 0

    with IMAPClient(IMAP_HOST, port=IMAP_PORT, ssl=True) as client:
        client.login(MAILRU_EMAIL, MAILRU_PASSWORD)
        log.info("Авторизация успешна")

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
                reply_body    = format_reply(patient_name, email_date, interpretation)

                # Сохраняем в папку "rezalt LAB moimed" на marimigi@mail.ru
                save_to_dest_folder(reply_subject, reply_body)

                # Помечаем исходное письмо как прочитанное
                client.set_flags([msg_id], ["\\Seen"])
                processed += 1

            except Exception as e:
                log.exception("Ошибка #%s: %s", msg_id, e)
                errors += 1

    log.info("=== Готово: обработано %d, ошибок %d ===", processed, errors)


if __name__ == "__main__":
    run()
