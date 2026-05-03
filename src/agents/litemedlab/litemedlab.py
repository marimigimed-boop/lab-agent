"""
litemedlab — агент интерпретации лабораторных анализов клиники ЛайтМед
Читает письма из папки "ДИАЛАБ ЛАБОРАТОРИЯ_РЕЗУЛЬТАТЫ" на litemed@mail.ru,
интерпретирует анализы через Claude API и сохраняет результат
на marimigi@mail.ru в папку "litemed LAB rezalt".
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
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.utils.word_builder import build_email_with_word

import anthropic
import pdfplumber
from dotenv import load_dotenv
from imapclient import IMAPClient
import os

env_path = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(env_path)

MAILRU_EMAIL    = os.environ["LITEMED_EMAIL"]
MAILRU_PASSWORD = os.environ["LITEMED_PASSWORD"]
ANTHROPIC_KEY   = os.environ["ANTHROPIC_API_KEY"]
MAILRU_FOLDER   = os.getenv("LITEMED_FOLDER", "ДИАЛАБ ЛАБОРАТОРИЯ_РЕЗУЛЬТАТЫ")
DEST_EMAIL      = os.getenv("DEST_EMAIL", "marimigi@mail.ru")
DEST_PASSWORD   = os.environ["DEST_PASSWORD"]
DEST_FOLDER     = os.getenv("LITEMED_DEST_FOLDER", "litemed LAB rezalt")

IMAP_HOST = "imap.mail.ru"
IMAP_PORT = 993

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "litemedlab.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("litemedlab")

claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)


def extract_pdf_text(pdf_bytes: bytes) -> str:
    text_parts: list[str] = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts) if text_parts else "[PDF не содержит текста]"


def decode_filename(raw: str) -> str:
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    return "".join(
        p.decode(e or "utf-8", errors="replace") if isinstance(p, bytes) else p
        for p, e in parts
    )


def is_pdf_part(content_type: str, filename: str) -> bool:
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
• Ферритин: муж 20–250 мкг/л, жен 10–120 мкг/л (дефицит <12)
• ОЖСС: 45–77 мкмоль/л
• Трансферрин: 2,0–3,6 г/л
• Кальций общий: 2,15–2,55 ммоль/л (⚠️ <1,75 или >3,5 — критично)
• Кальций ионизированный: 1,15–1,35 ммоль/л
• Фосфор: взрослые 0,81–1,45 ммоль/л; дети 1,3–2,1
• Магний: 0,70–1,05 ммоль/л
• Натрий: 136–145 ммоль/л (⚠️ <125 или >155 — критично)
• Калий: 3,5–5,1 ммоль/л (⚠️ <2,8 или >6,2 — критично для сердца)
• Хлор: 97–108 ммоль/л
• С-реактивный белок (СРБ): <5 мг/л
• Прокальцитонин: <0,1 нг/мл норма; >0,5 бактериальная инфекция; >2,0 ⚠️ сепсис
• Фибриноген: 2,0–4,0 г/л
• D-димер: <0,5 мкг/мл (FEU)
• МНО (INR): норма 0,85–1,15
• АЧТВ: 25–37 сек
• Амилаза: 25–125 Ед/л
• Липаза: 13–60 Ед/л
• ЛДГ: 125–243 Ед/л

ЩИТОВИДНАЯ ЖЕЛЕЗА:
• ТТГ: 0,4–4,0 мМЕ/л; при беременности: I триместр 0,1–2,5; II 0,2–3,0; III 0,3–3,5
• Св. Т4: 9,0–19,1 пмоль/л
• Св. Т3: 2,6–5,7 пмоль/л
• АТ-ТПО: <34 МЕ/мл
• АТ-ТГ: <115 МЕ/мл

ГОРМОНЫ:
• Кортизол утренний: 138–635 нмоль/л
• Инсулин натощак: 2,6–24,9 мкЕд/мл; HOMA-IR <2,7
• 25-OH витамин D: дефицит <20 нг/мл; недостаточность 20–30; норма 30–100

АЛЛЕРГОЛОГИЯ:
• Общий IgE: взрослые <100 МЕ/мл; дети до 1 года <15; 1–5 лет <60; 6–9 лет <90; 10–16 лет <200
• Специфические IgE: класс 0 (<0,35) — нет; класс 1–2 (0,35–3,5) — слабая/умеренная; класс 3–6 (>3,5) — выраженная

МОЧЕВОЙ ОСАДОК:
• Белок: <0,14 г/л
• Лейкоциты: <5 в п/зр (мужчины), <7 (женщины)
• Эритроциты: 0–2 в п/зр

═══════════════════════════════════════════
ФОРМАТ ОТВЕТА
═══════════════════════════════════════════

## Пациент: [ФИО] | [возраст] | [пол]
## Тип анализа: [название]
## Дата: [дата]

### ПОКАЗАТЕЛИ:
| Показатель | Результат | Референс | Статус |
|---|---|---|---|

### КЛИНИЧЕСКАЯ ИНТЕРПРЕТАЦИЯ:
[Связная интерпретация отклонений, их возможные причины]

### РЕКОМЕНДАЦИИ:
[Конкретные действия]

### ⚠️ КРИТИЧНЫЕ ЗНАЧЕНИЯ (если есть):
[Что требует немедленного реагирования]

---
Правила:
- Не ставить диагнозы — только интерпретация данных
- Учитывать возраст и пол пациента при оценке норм
- Если значение в бланке имеет собственный референс — использовать его
- Язык ответа: русский"""


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


def save_to_dest_folder(subject: str, patient_name: str, email_date: str,
                        interpretation: str, analysis_count: int = 1) -> None:
    """Сохраняет письмо с Word-вложением в папку DEST_FOLDER на DEST_EMAIL."""
    raw = build_email_with_word(
        from_addr=MAILRU_EMAIL,
        to_addr=DEST_EMAIL,
        subject=subject,
        patient_name=patient_name,
        date_str=email_date,
        analysis_count=analysis_count,
        interpretation_text=interpretation,
    )
    with IMAPClient(IMAP_HOST, port=IMAP_PORT, ssl=True) as dest:
        dest.login(DEST_EMAIL, DEST_PASSWORD)
        if not dest.folder_exists(DEST_FOLDER):
            dest.create_folder(DEST_FOLDER)
            log.info("  Папка '%s' создана на %s", DEST_FOLDER, DEST_EMAIL)
        dest.append(DEST_FOLDER, raw, flags=["\\Seen"])
        log.info("  Сохранено в '%s' на %s (Word вложение)", DEST_FOLDER, DEST_EMAIL)
