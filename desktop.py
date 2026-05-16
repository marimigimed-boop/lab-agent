"""
Десктоп-приложение Лаб-агента — запускается через запустить_десктоп.bat
"""
import sys
import os
import email
import email.header
import threading
import queue
from email.utils import parsedate_to_datetime
from email.message import EmailMessage
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import customtkinter as ctk
from imapclient import IMAPClient
import anthropic

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
DEST_PASSWORD = os.environ["DEST_PASSWORD"]

CLINIC_CONFIG = {
    "МОЙ МЕД": {
        "key":         "moimed",
        "email":       os.getenv("MAILRU_EMAIL", "moimed23@mail.ru"),
        "password":    os.environ["MAILRU_PASSWORD"],
        "folder":      os.getenv("MAILRU_FOLDER", "ЛАБОРАТОРИЯ ДИАЛАБ"),
        "dest_folder": os.getenv("DEST_FOLDER", "rezalt LAB moimed"),
    },
    "ЛайтМед": {
        "key":         "litemed",
        "email":       os.getenv("LITEMED_EMAIL", "litemed@mail.ru"),
        "password":    os.environ["LITEMED_PASSWORD"],
        "folder":      os.getenv("LITEMED_FOLDER", "ДИАЛАБ ЛАБОРАТОРИЯ_РЕЗУЛЬТАТЫ"),
        "dest_folder": os.getenv("LITEMED_DEST_FOLDER", "litemed LAB rezalt"),
    },
}

claude_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# ── Вспомогательные функции ────────────────────────────────────────────────────

def decode_header_str(raw: str) -> str:
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    return "".join(
        p.decode(e or "utf-8", errors="replace") if isinstance(p, bytes) else p
        for p, e in parts
    )


def search_patient_emails(cfg: dict, patient_fragment: str) -> list[bytes]:
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


def save_word_to_email(cfg: dict, patient_fragment: str, results: list[dict]) -> None:
    docx     = build_multi_patient_word_bytes(
        patients=results,
        title=f"ИНТЕРПРЕТАЦИЯ ЛАБОРАТОРНЫХ АНАЛИЗОВ — {patient_fragment.upper()}",
    )
    ts       = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"Интерпретация_{patient_fragment}_{ts}.docx"
    count    = len(results)
    subject  = (
        f"[{patient_fragment}] Интерпретация "
        f"({count} анализ{'а' if 2 <= count <= 4 else 'ов' if count > 4 else ''})"
    )
    msg = EmailMessage()
    msg["From"]    = cfg["email"]
    msg["To"]      = DEST_EMAIL
    msg["Subject"] = subject
    msg["Date"]    = email.utils.formatdate()
    msg.set_content(
        f"Пациент: {patient_fragment}\nДата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
        f"Результаты во вложении.",
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


# ── Главное окно ───────────────────────────────────────────────────────────────

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


class LabAgentApp(ctk.CTk):

    def __init__(self):
        super().__init__()

        self.title("Лаб-агент — Интерпретация анализов")
        self.geometry("1100x700")
        self.minsize(900, 600)
        self.configure(fg_color="#F0F7FF")

        self._results   = []
        self._queue     = queue.Queue()
        self._running   = False

        self._build_ui()
        self._poll_queue()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Левая панель
        self.sidebar = ctk.CTkFrame(
            self, width=260, corner_radius=0,
            fg_color="#1565C0",
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Логотип
        ctk.CTkLabel(
            self.sidebar, text="🔬", font=ctk.CTkFont(size=52),
            text_color="white", fg_color="transparent",
        ).pack(pady=(30, 0))

        ctk.CTkLabel(
            self.sidebar, text="ЛАБ-АГЕНТ",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="white", fg_color="transparent",
        ).pack(pady=(4, 2))

        ctk.CTkLabel(
            self.sidebar, text="Интерпретация анализов",
            font=ctk.CTkFont(size=11),
            text_color="#BBDEFB", fg_color="transparent",
        ).pack(pady=(0, 20))

        # Разделитель
        ctk.CTkFrame(self.sidebar, height=1, fg_color="#1976D2").pack(
            fill="x", padx=20, pady=10
        )

        # Выбор клиники
        ctk.CTkLabel(
            self.sidebar, text="КЛИНИКА",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#90CAF9", fg_color="transparent",
        ).pack(anchor="w", padx=20, pady=(10, 4))

        self.clinic_var = ctk.StringVar(value="МОЙ МЕД")
        for clinic in CLINIC_CONFIG:
            ctk.CTkRadioButton(
                self.sidebar,
                text=clinic,
                variable=self.clinic_var,
                value=clinic,
                font=ctk.CTkFont(size=13),
                text_color="white",
                fg_color="#64B5F6",
                border_color="#90CAF9",
                hover_color="#1976D2",
            ).pack(anchor="w", padx=24, pady=4)

        # Разделитель
        ctk.CTkFrame(self.sidebar, height=1, fg_color="#1976D2").pack(
            fill="x", padx=20, pady=14
        )

        # Поле пациента
        ctk.CTkLabel(
            self.sidebar, text="ПАЦИЕНТ",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#90CAF9", fg_color="transparent",
        ).pack(anchor="w", padx=20, pady=(0, 6))

        self.patient_entry = ctk.CTkEntry(
            self.sidebar,
            placeholder_text="Введите фамилию...",
            font=ctk.CTkFont(size=13),
            height=38,
            border_color="#42A5F5",
            fg_color="#0D47A1",
            text_color="white",
            placeholder_text_color="#90CAF9",
        )
        self.patient_entry.pack(fill="x", padx=20, pady=(0, 14))
        self.patient_entry.bind("<Return>", lambda e: self._start())

        # Кнопка
        self.search_btn = ctk.CTkButton(
            self.sidebar,
            text="🔍  Интерпретировать",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=42,
            fg_color="#1976D2",
            hover_color="#0D47A1",
            border_width=2,
            border_color="#64B5F6",
            corner_radius=10,
            command=self._start,
        )
        self.search_btn.pack(fill="x", padx=20, pady=(0, 10))

        # Кнопка очистки
        ctk.CTkButton(
            self.sidebar,
            text="🗑  Очистить",
            font=ctk.CTkFont(size=12),
            height=32,
            fg_color="transparent",
            hover_color="#1976D2",
            border_width=1,
            border_color="#42A5F5",
            text_color="#90CAF9",
            corner_radius=8,
            command=self._clear,
        ).pack(fill="x", padx=20)

        # Версия
        ctk.CTkLabel(
            self.sidebar,
            text="Claude Opus · 2026",
            font=ctk.CTkFont(size=10),
            text_color="#5C8CD6",
            fg_color="transparent",
        ).pack(side="bottom", pady=16)

        # ── Правая область ─────────────────────────────────────────────────────

        self.main = ctk.CTkFrame(self, corner_radius=0, fg_color="#F0F7FF")
        self.main.pack(side="right", fill="both", expand=True)

        # Шапка
        header = ctk.CTkFrame(self.main, corner_radius=12, fg_color="#1565C0", height=70)
        header.pack(fill="x", padx=20, pady=(16, 0))
        header.pack_propagate(False)

        ctk.CTkLabel(
            header,
            text="  МОЙ МЕД / ЛайтМед — Лабораторные анализы",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="white",
            fg_color="transparent",
        ).pack(side="left", padx=20, pady=0)

        self.clinic_badge = ctk.CTkLabel(
            header,
            text="МОЙ МЕД",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#1565C0",
            fg_color="#E3F2FD",
            corner_radius=20,
        )
        self.clinic_badge.pack(side="right", padx=20, pady=0, ipadx=12, ipady=4)

        # Статус-строка
        self.status_frame = ctk.CTkFrame(
            self.main, corner_radius=8, fg_color="#E3F2FD", height=40
        )
        self.status_frame.pack(fill="x", padx=20, pady=10)
        self.status_frame.pack_propagate(False)

        self.status_label = ctk.CTkLabel(
            self.status_frame,
            text="  Введите фамилию пациента и нажмите «Интерпретировать»",
            font=ctk.CTkFont(size=13),
            text_color="#1565C0",
            fg_color="transparent",
            anchor="w",
        )
        self.status_label.pack(fill="both", expand=True, padx=10)

        # Прогресс-бар
        self.progress = ctk.CTkProgressBar(self.main, mode="indeterminate", height=4)
        self.progress.pack(fill="x", padx=20, pady=(0, 6))
        self.progress.set(0)

        # Область вывода
        self.output = ctk.CTkTextbox(
            self.main,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            wrap="word",
            fg_color="white",
            text_color="#1A237E",
            border_color="#BBDEFB",
            border_width=1,
            corner_radius=12,
            activate_scrollbars=True,
        )
        self.output.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        self.output.configure(state="disabled")

        # Приветствие
        self._write_welcome()

    # ── Логика ─────────────────────────────────────────────────────────────────

    def _write_welcome(self):
        self.output.configure(state="normal")
        self.output.insert("end",
            "🔬  Лаб-агент готов к работе\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Выберите клинику в левой панели,\n"
            "введите фамилию пациента и нажмите «Интерпретировать».\n\n"
            "Агент найдёт письма с анализами и расшифрует каждый показатель.\n"
        )
        self.output.configure(state="disabled")

    def _set_status(self, text: str, color: str = "#1565C0"):
        self.status_label.configure(text=f"  {text}", text_color=color)

    def _clear(self):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")
        self._set_status("Введите фамилию пациента и нажмите «Интерпретировать»")
        self._results = []

    def _start(self):
        if self._running:
            return
        patient = self.patient_entry.get().strip()
        if not patient:
            self._set_status("Введите фамилию пациента!", "#C62828")
            return

        clinic_name = self.clinic_var.get()
        cfg = CLINIC_CONFIG[clinic_name]

        self.clinic_badge.configure(text=clinic_name)
        self._running = True
        self.search_btn.configure(state="disabled", text="⏳  Работаю...")
        self.progress.start()
        self._results = []

        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")

        thread = threading.Thread(
            target=self._worker,
            args=(cfg, patient),
            daemon=True,
        )
        thread.start()

    def _worker(self, cfg: dict, patient: str):
        try:
            self._queue.put(("status", f"🔎 Ищу письма «{patient}»...", "#1565C0"))

            raw_emails = search_patient_emails(cfg, patient)

            if not raw_emails:
                self._queue.put(("status", f"Писем с «{patient}» не найдено", "#C62828"))
                self._queue.put(("append", f"\n❌ Письма с «{patient}» не найдены в папке {cfg['folder']}\n"))
                self._queue.put(("done", None))
                return

            self._queue.put(("status", f"Найдено писем: {len(raw_emails)} · Интерпретирую...", "#1565C0"))

            for raw_email in raw_emails:
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

                self._queue.put(("append",
                    f"\n{'━'*60}\n"
                    f"  📋 {patient_name}  |  {email_date}\n"
                    f"{'━'*60}\n\n"
                ))

                user_msg = (
                    f"Пациент: {patient_name}\n"
                    f"Письмо от: {from_addr}\n"
                    f"Дата письма: {email_date}\n\n"
                    f"СОДЕРЖИМОЕ ПИСЬМА И ВЛОЖЕНИЙ:\n{full_content}\n\n"
                    "Проведи интерпретацию всех лабораторных показателей из этих данных."
                )

                full_text = ""
                with claude_client.messages.stream(
                    model="claude-opus-4-7",
                    max_tokens=2048,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_msg}],
                ) as stream:
                    for chunk in stream.text_stream:
                        full_text += chunk
                        self._queue.put(("append", chunk))

                self._results.append({
                    "name":           patient_name,
                    "date":           email_date,
                    "order":          "",
                    "analysis_count": 1,
                    "interpretation": full_text,
                })

            # Сохраняем Word
            if self._results:
                self._queue.put(("status", "💾 Сохраняю Word на почту...", "#1565C0"))
                self._queue.put(("append", f"\n{'━'*60}\n💾 Сохраняю Word-документ на почту...\n"))
                try:
                    save_word_to_email(cfg, patient, self._results)
                    self._queue.put(("append",
                        f"✅ Word сохранён в папку «{cfg['dest_folder']}» на {DEST_EMAIL}\n"
                    ))
                    self._queue.put(("status", f"✅ Готово! Word сохранён на {DEST_EMAIL}", "#2E7D32"))
                except Exception as e:
                    self._queue.put(("append", f"⚠️ Word не сохранился: {e}\n"))
                    self._queue.put(("status", "Интерпретация готова (Word не сохранился)", "#F57F17"))

        except Exception as e:
            self._queue.put(("status", f"Ошибка: {e}", "#C62828"))
            self._queue.put(("append", f"\n❌ Ошибка: {e}\n"))

        finally:
            self._queue.put(("done", None))

    def _poll_queue(self):
        try:
            while True:
                msg_type, data, *extra = self._queue.get_nowait() + (None,)
                if msg_type == "status":
                    color = extra[0] if extra else "#1565C0"
                    self._set_status(data, color)
                elif msg_type == "append":
                    self.output.configure(state="normal")
                    self.output.insert("end", data)
                    self.output.see("end")
                    self.output.configure(state="disabled")
                elif msg_type == "done":
                    self._running = False
                    self.search_btn.configure(state="normal", text="🔍  Интерпретировать")
                    self.progress.stop()
                    self.progress.set(0)
        except queue.Empty:
            pass
        self.after(50, self._poll_queue)

    def _poll_queue(self):
        try:
            while True:
                item = self._queue.get_nowait()
                msg_type = item[0]
                data     = item[1] if len(item) > 1 else None
                color    = item[2] if len(item) > 2 else "#1565C0"

                if msg_type == "status":
                    self._set_status(data, color)
                elif msg_type == "append":
                    self.output.configure(state="normal")
                    self.output.insert("end", data)
                    self.output.see("end")
                    self.output.configure(state="disabled")
                elif msg_type == "done":
                    self._running = False
                    self.search_btn.configure(state="normal", text="🔍  Интерпретировать")
                    self.progress.stop()
                    self.progress.set(0)
        except queue.Empty:
            pass
        self.after(50, self._poll_queue)


if __name__ == "__main__":
    app = LabAgentApp()
    app.mainloop()
