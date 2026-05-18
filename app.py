"""
Веб-интерфейс лаб-агента — запускается через запустить_веб.bat
"""
import sys
import os
import email
import email.header
from email.utils import parsedate_to_datetime
from email.message import EmailMessage
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import streamlit as st

# Загружаем секреты Streamlit Cloud в os.environ (для облачного запуска)
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:
    pass

import anthropic
from imapclient import IMAPClient

from src.agents.moimedlab.moimedlab import (
    SYSTEM_PROMPT,
    extract_email_content,
    decode_subject,
    build_full_content,
)
from src.utils.word_builder import build_multi_patient_word_bytes

# ── Настройки ──────────────────────────────────────────────────────────────────

IMAP_HOST = "imap.mail.ru"
IMAP_PORT  = 993

DEST_EMAIL    = os.getenv("DEST_EMAIL", "marimigi@mail.ru")
DEST_PASSWORD = os.getenv("DEST_PASSWORD", "")

CLINIC_CONFIG = {
    "moimed": {
        "label":       "МОЙ МЕД",
        "icon":        "🏥",
        "email":       os.getenv("MAILRU_EMAIL", "moimed23@mail.ru"),
        "password":    os.getenv("MAILRU_PASSWORD", ""),
        "folder":      os.getenv("MAILRU_FOLDER", "ЛАБОРАТОРИЯ ДИАЛАБ"),
        "dest_folder": os.getenv("DEST_FOLDER", "rezalt LAB moimed"),
        "color":       "#1565C0",
    },
    "litemed": {
        "label":       "ЛайтМед",
        "icon":        "🏨",
        "email":       os.getenv("LITEMED_EMAIL", "litemed@mail.ru"),
        "password":    os.getenv("LITEMED_PASSWORD", ""),
        "folder":      os.getenv("LITEMED_FOLDER", "ДИАЛАБ ЛАБОРАТОРИЯ_РЕЗУЛЬТАТЫ"),
        "dest_folder": os.getenv("LITEMED_DEST_FOLDER", "litemed LAB rezalt"),
        "color":       "#0277BD",
    },
}

_api_key = os.getenv("ANTHROPIC_API_KEY", "")
if not _api_key:
    st.error("⚠️ Не настроены секреты. Откройте Manage app → Settings → Secrets и добавьте пароли.")
    st.stop()

claude_client = anthropic.Anthropic(api_key=_api_key)

# ── CSS ────────────────────────────────────────────────────────────────────────

CUSTOM_CSS = """
<style>
/* Основные цвета */
:root {
    --primary:      #1565C0;
    --primary-light:#1976D2;
    --primary-dark: #0D47A1;
    --accent:       #E3F2FD;
    --success:      #2E7D32;
    --warning:      #F57F17;
    --error:        #C62828;
    --text:         #1A237E;
    --text-light:   #546E7A;
    --border:       #BBDEFB;
    --bg-card:      #FFFFFF;
    --bg-page:      #F0F7FF;
}

/* Фон страницы */
.stApp {
    background: var(--bg-page);
}

/* Боковая панель */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0D47A1 0%, #1565C0 60%, #1976D2 100%);
    border-right: none;
}
section[data-testid="stSidebar"] * {
    color: white !important;
}
section[data-testid="stSidebar"] .stRadio label {
    color: rgba(255,255,255,0.9) !important;
    font-size: 15px;
}
/* Поле ввода — белый фон, тёмный текст (надёжно в любой версии Streamlit) */
section[data-testid="stSidebar"] input,
section[data-testid="stSidebar"] input[type="text"],
section[data-testid="stSidebar"] textarea {
    background-color: white !important;
    color: #1a237e !important;
    caret-color: #1a237e !important;
    border: 2px solid rgba(255,255,255,0.7) !important;
    border-radius: 8px !important;
}
section[data-testid="stSidebar"] [data-baseweb="base-input"],
section[data-testid="stSidebar"] [data-baseweb="input"],
section[data-testid="stSidebar"] [data-testid="stTextInputRootElement"] {
    background-color: white !important;
    border-radius: 8px !important;
}
section[data-testid="stSidebar"] input::placeholder {
    color: #90a4ae !important;
}
section[data-testid="stSidebar"] .stTextInput label,
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] {
    color: rgba(255,255,255,0.9) !important;
    font-weight: 600 !important;
}

/* Кнопка поиска */
section[data-testid="stSidebar"] .stButton button {
    background: rgba(255,255,255,0.2) !important;
    color: white !important;
    border: 2px solid rgba(255,255,255,0.6) !important;
    border-radius: 10px !important;
    font-weight: 700 !important;
    font-size: 16px !important;
    padding: 12px !important;
    width: 100% !important;
    transition: all 0.2s ease;
}
section[data-testid="stSidebar"] .stButton button:hover {
    background: rgba(255,255,255,0.35) !important;
    border-color: white !important;
}

/* Заголовок приложения */
.app-header {
    background: linear-gradient(135deg, #0D47A1 0%, #1565C0 100%);
    border-radius: 16px;
    padding: 24px 32px;
    margin-bottom: 24px;
    color: white;
    box-shadow: 0 4px 20px rgba(21,101,192,0.3);
}
.app-header h1 {
    margin: 0 0 4px 0;
    font-size: 26px;
    font-weight: 800;
    color: white;
}
.app-header p {
    margin: 0;
    font-size: 14px;
    opacity: 0.85;
    color: white;
}

/* Карточки результатов */
.result-card {
    background: white;
    border-radius: 14px;
    padding: 24px;
    margin-bottom: 20px;
    border-left: 5px solid #1565C0;
    box-shadow: 0 2px 12px rgba(21,101,192,0.12);
}
.result-card-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 12px;
    padding-bottom: 12px;
    border-bottom: 1px solid #E3F2FD;
}
.result-card-title {
    font-size: 18px;
    font-weight: 700;
    color: #0D47A1;
    margin: 0;
}
.result-card-date {
    font-size: 13px;
    color: #78909C;
    background: #F0F7FF;
    padding: 3px 10px;
    border-radius: 20px;
}

/* Метки клиники */
.clinic-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 700;
    background: #E3F2FD;
    color: #1565C0;
    margin-bottom: 16px;
}

/* Статус-бар */
.status-bar {
    background: #E3F2FD;
    border-radius: 10px;
    padding: 14px 20px;
    margin-bottom: 20px;
    border-left: 4px solid #1565C0;
    color: #0D47A1;
    font-weight: 600;
}

/* Успех */
.success-box {
    background: #E8F5E9;
    border-radius: 10px;
    padding: 14px 20px;
    border-left: 4px solid #2E7D32;
    color: #1B5E20;
    font-weight: 600;
}

/* Пустой стейт */
.empty-state {
    text-align: center;
    padding: 60px 20px;
    color: #90A4AE;
}
.empty-state .icon {
    font-size: 64px;
    margin-bottom: 16px;
}
.empty-state h3 {
    color: #78909C;
    font-weight: 600;
}

/* Разделитель */
.sidebar-section {
    margin: 20px 0;
    padding-top: 16px;
    border-top: 1px solid rgba(255,255,255,0.2);
}
.sidebar-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    opacity: 0.7;
    margin-bottom: 8px;
    font-weight: 600;
}

/* Логотип в сайдбаре */
.sidebar-logo {
    text-align: center;
    padding: 10px 0 20px 0;
}
.sidebar-logo .icon {
    font-size: 48px;
    display: block;
}
.sidebar-logo h2 {
    font-size: 20px;
    font-weight: 800;
    margin: 8px 0 4px 0;
    color: white;
}
.sidebar-logo p {
    font-size: 12px;
    opacity: 0.7;
    margin: 0;
    color: white;
}

/* Стриминг текста */
div[data-testid="stMarkdownContainer"] table {
    border-collapse: collapse;
    width: 100%;
    margin: 12px 0;
    font-size: 14px;
}
div[data-testid="stMarkdownContainer"] th {
    background: #E3F2FD;
    color: #0D47A1;
    padding: 8px 12px;
    font-weight: 700;
    border: 1px solid #BBDEFB;
}
div[data-testid="stMarkdownContainer"] td {
    padding: 7px 12px;
    border: 1px solid #E3F2FD;
}
div[data-testid="stMarkdownContainer"] tr:nth-child(even) td {
    background: #F8FBFF;
}

/* Скрыть меню streamlit */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
</style>
"""

# ── Вспомогательные функции ────────────────────────────────────────────────────

def decode_header_str(raw: str) -> str:
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    return "".join(
        p.decode(e or "utf-8", errors="replace") if isinstance(p, bytes) else p
        for p, e in parts
    )


def search_patient_emails(clinic_key: str, patient_fragment: str) -> list[bytes]:
    cfg = CLINIC_CONFIG[clinic_key]

    # IMAP LOGIN требует ASCII — проверяем пароль до подключения
    try:
        cfg["password"].encode("ascii")
    except UnicodeEncodeError:
        raise ValueError(
            "Пароль содержит нелатинские символы (кириллица/грузинский). "
            "Откройте Streamlit Cloud → Manage app → Settings → Secrets "
            "и убедитесь, что пароль написан латинскими буквами."
        )

    raw_emails = []

    with IMAPClient(IMAP_HOST, port=IMAP_PORT, ssl=True) as client:
        client.login(cfg["email"], cfg["password"])
        client.select_folder(cfg["folder"])

        all_ids = client.search(["ALL"])
        found_ids = []
        for msg_id in all_ids:
            raw     = client.fetch([msg_id], ["ENVELOPE"])
            subj_raw = raw[msg_id][b"ENVELOPE"].subject or b""
            subject = decode_header_str(
                subj_raw.decode("utf-8", errors="replace")
                if isinstance(subj_raw, bytes) else str(subj_raw)
            )
            if patient_fragment.lower() in subject.lower():
                found_ids.append(msg_id)

        for msg_id in found_ids:
            data = client.fetch([msg_id], ["RFC822"])
            raw_emails.append(data[msg_id][b"RFC822"])

    return raw_emails


def stream_interpretation(patient_name: str, from_addr: str,
                          email_date: str, content: str):
    user_msg = (
        f"Пациент: {patient_name}\n"
        f"Письмо от: {from_addr}\n"
        f"Дата письма: {email_date}\n\n"
        f"СОДЕРЖИМОЕ ПИСЬМА И ВЛОЖЕНИЙ:\n{content}\n\n"
        "Проведи интерпретацию всех лабораторных показателей из этих данных."
    )
    with claude_client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        for text in stream.text_stream:
            yield text


def save_word_to_email(clinic_key: str, patient_fragment: str,
                       results: list[dict]) -> None:
    cfg   = CLINIC_CONFIG[clinic_key]
    docx  = build_multi_patient_word_bytes(
        patients=results,
        title=f"ИНТЕРПРЕТАЦИЯ ЛАБОРАТОРНЫХ АНАЛИЗОВ — {patient_fragment.upper()}",
    )
    ts       = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"Интерпретация_{patient_fragment}_{ts}.docx"
    count    = len(results)
    subject  = (
        f"[{cfg['label']}] Интерпретация — {patient_fragment} "
        f"({count} анализ{'а' if 2 <= count <= 4 else 'ов' if count > 4 else ''})"
    )

    msg = EmailMessage()
    msg["From"]    = cfg["email"]
    msg["To"]      = DEST_EMAIL
    msg["Subject"] = subject
    msg["Date"]    = email.utils.formatdate()
    msg.set_content(
        f"Пациент: {patient_fragment}\n"
        f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"Результаты во вложении (.docx).\n\nКлиника {cfg['label']}",
        charset="utf-8",
    )
    msg.add_attachment(
        docx,
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )
    with IMAPClient(IMAP_HOST, port=IMAP_PORT, ssl=True) as dest:
        dest.login(DEST_EMAIL, DEST_PASSWORD)
        if not dest.folder_exists(cfg["dest_folder"]):
            dest.create_folder(cfg["dest_folder"])
        dest.append(cfg["dest_folder"], msg.as_bytes(), flags=["\\Seen"])


# ── Интерфейс ──────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Лаб-агент | МОЙ МЕД",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ── Боковая панель ─────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
    <div class="sidebar-logo">
        <span class="icon">🔬</span>
        <h2>ЛАБ-АГЕНТ</h2>
        <p>Интерпретация анализов</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="sidebar-label">Выберите клинику</div>', unsafe_allow_html=True)
    clinic_label = st.radio(
        label="Клиника",
        options=["🏥  МОЙ МЕД", "🏨  ЛайтМед"],
        index=0,
        label_visibility="collapsed",
    )
    clinic_key = "moimed" if "МОЙ МЕД" in clinic_label else "litemed"

    st.markdown('<div class="sidebar-section"></div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-label">Поиск пациента</div>', unsafe_allow_html=True)

    patient = st.text_input(
        label="Фамилия пациента",
        placeholder="Введите фамилию...",
        label_visibility="collapsed",
    )

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    start = st.button(
        "🔍  Интерпретировать",
        disabled=not patient.strip(),
        use_container_width=True,
    )

    st.markdown('<div class="sidebar-section"></div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-label">Подсказка</div>', unsafe_allow_html=True)
    st.markdown("""
    <div style="font-size:12px; opacity:0.8; line-height:1.6;">
        Введите фамилию пациента или её часть. Агент найдёт все совпадения в почте и интерпретирует каждый анализ.
    </div>
    """, unsafe_allow_html=True)

# ── Главная область ────────────────────────────────────────────────────────────

cfg = CLINIC_CONFIG[clinic_key]

st.markdown(f"""
<div class="app-header">
    <h1>{cfg['icon']} {cfg['label']} — Лабораторные анализы</h1>
    <p>ИИ-интерпретация результатов на основе актуальных референсов 2024–2026 · Claude Opus</p>
</div>
""", unsafe_allow_html=True)

# Пустой стейт (нет поиска)
if not start or not patient.strip():
    st.markdown("""
    <div class="empty-state">
        <div class="icon">🧪</div>
        <h3>Введите фамилию пациента</h3>
        <p>В боковой панели слева введите фамилию и нажмите «Интерпретировать»</p>
    </div>
    """, unsafe_allow_html=True)

else:
    patient = patient.strip()

    # ── Поиск писем ───────────────────────────────────────────────────────────
    st.markdown(f"""
    <div class="status-bar">
        🔎 Ищу письма пациента <b>«{patient}»</b> в клинике <b>{cfg['label']}</b>…
    </div>
    """, unsafe_allow_html=True)

    with st.spinner("Подключаюсь к почте…"):
        try:
            raw_emails = search_patient_emails(clinic_key, patient)
        except Exception as e:
            st.error(f"Ошибка подключения к почте: {e}")
            st.stop()

    if not raw_emails:
        st.warning(f"Письма с «{patient}» не найдены в папке **{cfg['folder']}**")
        st.stop()

    st.markdown(f"""
    <div class="status-bar">
        ✅ Найдено писем: <b>{len(raw_emails)}</b> · Запускаю интерпретацию…
    </div>
    """, unsafe_allow_html=True)

    # ── Интерпретация ─────────────────────────────────────────────────────────
    results = []

    for i, raw_email in enumerate(raw_emails, 1):
        msg = email.message_from_bytes(raw_email)

        from_addr  = msg.get("From", "неизвестно")
        date_raw   = msg.get("Date", "")
        try:
            email_date = parsedate_to_datetime(date_raw).strftime("%d.%m.%Y")
        except Exception:
            email_date = date_raw or "дата неизвестна"

        body, attachments = extract_email_content(msg)
        patient_name      = decode_subject(msg)
        full_content      = build_full_content(body, attachments)

        if full_content == "[Письмо пустое, вложения отсутствуют]":
            continue

        st.markdown(f"""
        <div class="result-card">
            <div class="result-card-header">
                <span style="font-size:28px">📋</span>
                <div>
                    <p class="result-card-title">{patient_name}</p>
                    <span class="result-card-date">📅 {email_date}</span>
                    &nbsp;
                    <span class="clinic-badge">{cfg['icon']} {cfg['label']}</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        with st.container():
            interpretation = st.write_stream(
                stream_interpretation(patient_name, from_addr, email_date, full_content)
            )

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        results.append({
            "name":           patient_name,
            "date":           email_date,
            "order":          "",
            "analysis_count": 1,
            "interpretation": interpretation,
        })

    # ── Сохранение на почту ───────────────────────────────────────────────────
    if results:
        st.divider()
        with st.spinner("Сохраняю Word-документ на почту…"):
            try:
                save_word_to_email(clinic_key, patient, results)
                dest_folder = cfg["dest_folder"]
                st.markdown(f"""
                <div class="success-box">
                    ✅ Word-документ сохранён в папку <b>«{dest_folder}»</b> на {DEST_EMAIL}
                </div>
                """, unsafe_allow_html=True)
            except Exception as e:
                st.warning(f"Интерпретация выполнена, но Word не сохранился: {e}")
