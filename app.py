from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


APP_DIR = Path(__file__).resolve().parent
DB_NAME = Path(os.environ.get("DB_PATH", str(APP_DIR / "campaign.db")))
DEFAULT_MESSAGE = """Hello 👋🏾, This survey invitation is officially verified for your student contact number: {{Number}}

My name is Vincent Adzika, a Level 300 Computer Science student at Accra Technical University.

I'm currently working on a student initiative to better understand the experiences, challenges, and needs of Computer Science students at ATU.

The goal is to gather feedback from students across different levels so we can identify practical ways to improve our learning experience, especially regarding practical skills, opportunities beyond lectures, career development, and industry exposure.

I'd really appreciate it if you could take 3–5 minutes to complete this survey.

🔗 https://forms.gle

Thank you for your time 🙏🏾"""


st.set_page_config(page_title="WhatsApp CRM Batch Sender", layout="wide")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def init_db() -> None:
    with closing(connect()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                last_sent_at TEXT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO app_meta(key, value) VALUES ('duplicates_avoided', '0')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO app_meta(key, value) VALUES ('message_template', ?)" , (DEFAULT_MESSAGE,)
        )
        conn.execute(
            "INSERT OR IGNORE INTO app_meta(key, value) VALUES ('batch_size', '10')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO app_meta(key, value) VALUES ('page_size', '20')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO app_meta(key, value) VALUES ('view_mode', 'batch')"
        )
        conn.commit()


def get_meta(key: str, default: str = "0") -> str:
    with closing(connect()) as conn:
        row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default


def set_meta(key: str, value: str) -> None:
    with closing(connect()) as conn:
        conn.execute(
            "INSERT INTO app_meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()


def bump_meta(key: str, amount: int) -> None:
    current = int(get_meta(key, "0"))
    set_meta(key, str(current + amount))


def get_int_meta(key: str, default: int) -> int:
    try:
        return int(get_meta(key, str(default)))
    except ValueError:
        return default


def load_app_settings() -> dict[str, str]:
    return {
        "message_template": get_meta("message_template", DEFAULT_MESSAGE),
        "batch_size": str(get_int_meta("batch_size", 10)),
        "page_size": str(get_int_meta("page_size", 20)),
        "view_mode": get_meta("view_mode", "batch"),
    }


def save_app_setting(key: str, value: str) -> None:
    set_meta(key, value)


def save_message_template(template: str) -> None:
    save_app_setting("message_template", template)


def normalize_number(value: object) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None

    if text.endswith(".0"):
        text = text[:-2]

    text = text.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if text.startswith("+"):
        text = text[1:]

    if not re.fullmatch(r"\d+", text):
        return None

    if text.startswith("0") and len(text) == 10:
        text = "233" + text[1:]
    elif text.startswith("233") and len(text) == 12:
        pass
    else:
        return None

    return text if re.fullmatch(r"233\d{9}", text) else None


def read_contacts_file(uploaded_file) -> pd.DataFrame:
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(uploaded_file, header=None, dtype=str, usecols=[0])
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(uploaded_file, header=None, dtype=str, usecols=[0])
    raise ValueError("Only .csv and .xlsx files are supported")


def load_upload(uploaded_file) -> tuple[list[str], int, int]:
    frame = read_contacts_file(uploaded_file)
    if frame.empty:
        return [], 0, 0

    raw = frame.iloc[:, 0].tolist()
    cleaned: list[str] = []
    invalid = 0

    for value in raw:
        number = normalize_number(value)
        if number is None:
            invalid += 1
            continue
        cleaned.append(number)

    return cleaned, len(raw), invalid


def insert_contacts(numbers: list[str]) -> tuple[int, int]:
    if not numbers:
        return 0, 0

    seen: set[str] = set()
    added = 0
    duplicates = 0

    with closing(connect()) as conn:
        for number in numbers:
            if number in seen:
                duplicates += 1
                continue
            seen.add(number)

            exists = conn.execute("SELECT 1 FROM contacts WHERE phone = ? LIMIT 1", (number,)).fetchone()
            if exists:
                duplicates += 1
                continue

            cur = conn.execute(
                "INSERT OR IGNORE INTO contacts(phone, status, created_at, last_sent_at) VALUES(?, 'pending', ?, NULL)",
                (number, now_iso()),
            )
            if cur.rowcount == 1:
                added += 1
            else:
                duplicates += 1

        conn.commit()

    if duplicates:
        bump_meta("duplicates_avoided", duplicates)

    return added, duplicates


def fetch_contacts_by_phones(phones: list[str]) -> list[sqlite3.Row]:
    if not phones:
        return []

    placeholders = ",".join(["?"] * len(phones))
    sql = f"SELECT id, phone, status, created_at, last_sent_at FROM contacts WHERE phone IN ({placeholders}) ORDER BY id ASC"
    with closing(connect()) as conn:
        return conn.execute(sql, phones).fetchall()


def mark_done(contact_id: int) -> None:
    with closing(connect()) as conn:
        conn.execute(
            "UPDATE contacts SET status = 'done', last_sent_at = ? WHERE id = ?",
            (now_iso(), contact_id),
        )
        conn.commit()


def reset_campaign() -> None:
    with closing(connect()) as conn:
        conn.execute("UPDATE contacts SET status = 'pending', last_sent_at = NULL")
        conn.commit()
    set_meta("duplicates_avoided", "0")


def stats() -> dict[str, int]:
    with closing(connect()) as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending
            FROM contacts
            """
        ).fetchone()

    total = int(row["total"] or 0)
    done = int(row["done"] or 0)
    pending = int(row["pending"] or 0)
    duplicates_avoided = int(get_meta("duplicates_avoided", "0"))
    return {
        "total": total,
        "done": done,
        "pending": pending,
        "duplicates_avoided": duplicates_avoided,
    }


def fetch_pending(batch_size: int) -> list[sqlite3.Row]:
    with closing(connect()) as conn:
        return conn.execute(
            "SELECT id, phone, status, created_at, last_sent_at FROM contacts WHERE status = 'pending' ORDER BY id ASC LIMIT ?",
            (batch_size,),
        ).fetchall()


def fetch_contacts(search: str, status_filter: str, limit: int, offset: int) -> list[sqlite3.Row]:
    sql = "SELECT id, phone, status, created_at, last_sent_at FROM contacts WHERE 1=1"
    params: list[object] = []

    if search.strip():
        sql += " AND phone LIKE ?"
        params.append(f"%{search.strip()}%")
    if status_filter != "All":
        sql += " AND status = ?"
        params.append(status_filter.lower())

    sql += " ORDER BY id ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with closing(connect()) as conn:
        return conn.execute(sql, params).fetchall()


def count_contacts(search: str, status_filter: str) -> int:
    sql = "SELECT COUNT(*) AS total FROM contacts WHERE 1=1"
    params: list[object] = []

    if search.strip():
        sql += " AND phone LIKE ?"
        params.append(f"%{search.strip()}%")
    if status_filter != "All":
        sql += " AND status = ?"
        params.append(status_filter.lower())

    with closing(connect()) as conn:
        row = conn.execute(sql, params).fetchone()
        return int(row["total"] or 0)


def completed_export_df(search: str) -> pd.DataFrame:
    sql = "SELECT id, phone, status, created_at, last_sent_at FROM contacts WHERE status = 'done'"
    params: list[object] = []
    if search.strip():
        sql += " AND phone LIKE ?"
        params.append(f"%{search.strip()}%")
    sql += " ORDER BY last_sent_at DESC, id DESC"

    with closing(connect()) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def whatsapp_link(phone: str, message_template: str) -> str:
    message = message_template.replace("{{Number}}", phone)
    return f"whatsapp://send?phone={phone}&text={quote(message, safe='')}"


def launch_button(phone: str, message_template: str, dimmed: bool = False) -> None:
    url = whatsapp_link(phone, message_template)
    opacity = 0.45 if dimmed else 1.0
    components.html(
        f"""
        <div style="display:flex;width:100%;justify-content:center;">
          <a href="{url}" target="_self" rel="noopener noreferrer"
             style="display:inline-flex;align-items:center;justify-content:center;width:100%;padding:0.55rem 0.8rem;border-radius:0.75rem;background:#25D366;color:#fff;text-decoration:none;font-weight:800;opacity:{opacity};">
            Open WhatsApp
          </a>
        </div>
        """,
        height=54,
    )


def phone_html(phone: str, done: bool) -> str:
    if done:
        return f"<span style='color:#94a3b8;text-decoration:line-through;font-weight:700;'>{phone}</span>"
    return f"<span style='color:#0f172a;font-weight:700;'>{phone}</span>"


def status_html(status: str) -> str:
    if status == "done":
        return "<span style='display:inline-flex;padding:0.2rem 0.55rem;border-radius:999px;background:#e2e8f0;color:#475569;font-weight:800;font-size:0.78rem;'>Done</span>"
    return "<span style='display:inline-flex;padding:0.2rem 0.55rem;border-radius:999px;background:#dcfce7;color:#15803d;font-weight:800;font-size:0.78rem;'>Pending</span>"


def ensure_state() -> None:
    settings = load_app_settings()
    defaults = {
        "message_template_saved": settings["message_template"],
        "message_template_draft": settings["message_template"],
        "search_term": "",
        "status_filter": "All",
        "page_size": int(settings["page_size"]),
        "page_index": 1,
        "batch_size": int(settings["batch_size"]),
        "batch_queue": [],
        "summary": None,
        "import_preview": [],
        "view_mode": settings["view_mode"],
        "settings_saved": False,
        "settings_notice": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_page() -> None:
    st.session_state.page_index = 1


def paginate(total_items: int, page_size: int, page_index: int) -> tuple[int, int, int]:
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    page_index = max(1, min(page_index, total_pages))
    offset = (page_index - 1) * page_size
    return page_index, total_pages, offset


init_db()
ensure_state()


st.markdown(
    """
    <style>
        :root {
            --bg: #08111f;
            --panel: #101a2f;
            --panel-2: #16233d;
            --border: rgba(148,163,184,0.18);
            --text: #e5eefb;
            --muted: #9db0cc;
            --accent: #25D366;
            --accent-2: #1f6feb;
        }
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(37, 211, 102, 0.12), transparent 24%),
                radial-gradient(circle at top right, rgba(31, 111, 235, 0.14), transparent 22%),
                linear-gradient(180deg, #09111f 0%, #0b1220 100%);
            color: var(--text);
        }
        .block-container { padding-top: 1rem; padding-bottom: 2rem; }
        .hero {
            border: 1px solid var(--border);
            border-radius: 18px;
            padding: 1rem 1rem 0.85rem 1rem;
            background: linear-gradient(135deg, rgba(16,26,47,0.96), rgba(11,18,32,0.96));
            box-shadow: 0 12px 30px rgba(0,0,0,0.28);
            margin-bottom: 1rem;
        }
        .hero h1 { margin: 0; font-size: 2rem; letter-spacing: -0.04em; color: var(--text); }
        .hero p { margin: 0.3rem 0 0 0; color: var(--muted); }
        .section-title { font-size: 1rem; font-weight: 800; color: var(--text); margin: 0.1rem 0 0.35rem 0; }
        .subtle { color: var(--muted); font-size: 0.92rem; }
        .metric {
            border: 1px solid var(--border);
            border-radius: 16px;
            background: linear-gradient(180deg, rgba(16,26,47,0.95), rgba(13,21,37,0.98));
            padding: 0.95rem;
            box-shadow: 0 8px 22px rgba(0,0,0,0.24);
        }
        .metric-label { color: var(--muted); font-size: 0.77rem; text-transform: uppercase; letter-spacing: 0.08em; }
        .metric-value { color: var(--text); font-size: 1.7rem; font-weight: 800; margin-top: 0.15rem; }
        div[data-testid="stFileUploader"] {
            background: rgba(16,26,47,0.72);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 0.5rem;
        }
        div[data-testid="stTextInput"] input,
        div[data-testid="stSelectbox"] div,
        textarea {
            background-color: rgba(8,17,31,0.9) !important;
            color: var(--text) !important;
            border-color: var(--border) !important;
        }
        textarea { min-height: 180px; }
        button[kind="primary"], button[kind="secondary"] {
            border-radius: 0.85rem !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


st.markdown(
    """
    <div class="hero">
        <h1>📱 WhatsApp CRM Batch Sender</h1>
        <p>Fast mobile-first workflow: tap, open WhatsApp, send, mark done, next.</p>
    </div>
    """,
    unsafe_allow_html=True,
)


with st.sidebar:
    st.markdown('<div class="section-title">Settings</div>', unsafe_allow_html=True)
    st.selectbox("Mode", ["batch", "table"], key="view_mode")
    st.selectbox("Batch size", [5, 10, 20, 50], key="batch_size")
    st.selectbox("Rows per page", [10, 20, 50, 100], key="page_size")
    st.caption("Edit the message below, then apply it so the launch buttons use the new text.")
    if st.button("Save Settings", use_container_width=True):
        save_message_template(st.session_state.message_template_draft)
        save_app_setting("batch_size", str(int(st.session_state.batch_size)))
        save_app_setting("page_size", str(int(st.session_state.page_size)))
        save_app_setting("view_mode", st.session_state.view_mode)
        st.session_state.message_template_saved = st.session_state.message_template_draft
        st.session_state.settings_saved = True
        st.session_state.settings_notice = "Settings applied. WhatsApp buttons now use the updated message template."
        st.rerun()

    st.markdown('<div class="section-title">Upload Contacts</div>', unsafe_allow_html=True)
    with st.form("upload_form", clear_on_submit=False):
        uploaded_file = st.file_uploader("CSV or Excel", type=["csv", "xlsx", "xls"])
        upload_clicked = st.form_submit_button("Import Contacts")

    st.markdown('<div style="height:0.65rem"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Filters</div>', unsafe_allow_html=True)
    st.text_input("Search", key="search_term", on_change=reset_page, placeholder="Search phone digits")
    st.selectbox("Status", ["All", "Pending", "Done"], key="status_filter", on_change=reset_page)
    st.markdown('<div style="height:0.65rem"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Reset</div>', unsafe_allow_html=True)
    reset_confirm = st.checkbox("I understand this resets all contacts to pending")
    reset_clicked = st.button("Reset Completed Campaign", disabled=not reset_confirm, use_container_width=True)


if upload_clicked:
    if uploaded_file is None:
        st.error("Upload a .csv or .xlsx file first.")
    else:
        try:
            numbers, total_rows, invalid_count = load_upload(uploaded_file)
            added, duplicates = insert_contacts(numbers)
            st.session_state.import_preview = [dict(row) for row in fetch_contacts_by_phones(numbers)]
            st.session_state.summary = {
                "added": added,
                "duplicates": duplicates,
                "invalid": invalid_count,
                "rows": total_rows,
                "name": uploaded_file.name,
            }
            reset_page()
            st.rerun()
        except Exception as exc:
            st.error(f"Import failed: {exc}")


if reset_clicked:
    reset_campaign()
    st.session_state.summary = None
    st.session_state.import_preview = []
    reset_page()
    st.session_state.batch_queue = []
    st.rerun()


if st.session_state.summary:
    s = st.session_state.summary
    st.success(f"Imported {s['name']}: {s['added']} new contacts added")
    st.info(f"{s['duplicates']} duplicates skipped")
    if s["invalid"]:
        st.warning(f"{s['invalid']} invalid rows were ignored")


if st.session_state.settings_saved:
    st.info("Settings saved for this session and persisted to SQLite.")
    st.session_state.settings_saved = False

if st.session_state.settings_notice:
    st.success(st.session_state.settings_notice)
    st.session_state.settings_notice = ""


if st.session_state.import_preview:
    st.markdown('<div class="section-title">Imported Contacts Preview</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtle">These are the numbers extracted from the uploaded file. Use the buttons immediately below each row.</div>', unsafe_allow_html=True)
    for row in st.session_state.import_preview[:50]:
        done_flag = str(row["status"]).lower() == "done"
        c1, c2, c3 = st.columns([1, 2, 1])
        c1.markdown(phone_html(str(row["phone"]), done_flag), unsafe_allow_html=True)
        with c2:
            launch_button(str(row["phone"]), st.session_state.message_template_saved, dimmed=done_flag)
        if c3.button("Mark Done", key=f"import_done_{row['id']}", disabled=done_flag):
            mark_done(int(row["id"]))
            st.rerun()
        st.markdown("---")


metrics = stats()
total = metrics["total"]
done = metrics["done"]
pending = metrics["pending"]
duplicates_avoided = metrics["duplicates_avoided"]

metric_cols = st.columns(4)
metric_cols[0].markdown(f"<div class='metric'><div class='metric-label'>Total</div><div class='metric-value'>{total}</div></div>", unsafe_allow_html=True)
metric_cols[1].markdown(f"<div class='metric'><div class='metric-label'>Completed</div><div class='metric-value'>{done}</div></div>", unsafe_allow_html=True)
metric_cols[2].markdown(f"<div class='metric'><div class='metric-label'>Pending</div><div class='metric-value'>{pending}</div></div>", unsafe_allow_html=True)
metric_cols[3].markdown(f"<div class='metric'><div class='metric-label'>Duplicates Avoided</div><div class='metric-value'>{duplicates_avoided}</div></div>", unsafe_allow_html=True)

st.progress(done / total if total else 0)


st.markdown('<div class="section-title">Batch Sender</div>', unsafe_allow_html=True)
st.markdown('<div class="subtle">Tap Open WhatsApp, send the message, then mark the row done and move to the next contact.</div>', unsafe_allow_html=True)

batch_refresh = st.button("Load / Refresh Batch", use_container_width=True)
if batch_refresh:
    st.session_state.batch_queue = [dict(row) for row in fetch_pending(int(st.session_state.batch_size))]
    reset_page()

if st.session_state.view_mode == "batch":
    if not st.session_state.batch_queue:
        st.session_state.batch_queue = [dict(row) for row in fetch_pending(int(st.session_state.batch_size))]

    if st.session_state.batch_queue:
        st.caption(f"Showing next {len(st.session_state.batch_queue)} pending contacts")
        for row in list(st.session_state.batch_queue):
            phone = str(row["phone"])
            done_flag = str(row["status"]).lower() == "done"
            c1, c2, c3 = st.columns([1, 2, 1])
            c1.markdown(phone_html(phone, done_flag), unsafe_allow_html=True)
            with c2:
                launch_button(phone, st.session_state.message_template_saved, dimmed=done_flag)
            if c3.button("Mark Done", key=f"batch_done_{row['id']}", disabled=done_flag):
                mark_done(int(row["id"]))
                st.session_state.batch_queue = [item for item in st.session_state.batch_queue if int(item["id"]) != int(row["id"])]
                st.rerun()
            st.markdown("---")
    else:
        st.info("Load a batch to start sending.")
else:
    st.info("Table mode is active. Use the contacts table below for row-by-row processing.")


st.markdown('<div class="section-title">Message Template</div>', unsafe_allow_html=True)
st.session_state.message_template_draft = st.text_area(
    "Message Template",
    value=st.session_state.message_template_draft,
    height=340,
    label_visibility="collapsed",
)
if st.button("Apply Message Template", use_container_width=True):
    save_message_template(st.session_state.message_template_draft)
    st.session_state.message_template_saved = st.session_state.message_template_draft
    st.session_state.settings_notice = "Message template applied. Launch buttons now use the updated text."
    st.rerun()


st.markdown('<div class="section-title">Contacts Table</div>', unsafe_allow_html=True)
st.markdown('<div class="subtle">Completed rows are greyed out and struck through, but still show a launch button.</div>', unsafe_allow_html=True)

if st.session_state.view_mode == "table":
    total_filtered = count_contacts(st.session_state.search_term, st.session_state.status_filter)
    page_index, total_pages, offset = paginate(total_filtered, int(st.session_state.page_size), int(st.session_state.page_index))
    st.session_state.page_index = page_index

    nav1, nav2, nav3 = st.columns([1, 2, 1])
    if nav1.button("Previous", use_container_width=True, disabled=page_index <= 1):
        st.session_state.page_index = page_index - 1
        st.rerun()
    nav2.markdown(f"<div style='text-align:center;padding-top:0.45rem;font-weight:700;color:#9db0cc;'>Page {page_index} of {total_pages}</div>", unsafe_allow_html=True)
    if nav3.button("Next", use_container_width=True, disabled=page_index >= total_pages):
        st.session_state.page_index = page_index + 1
        st.rerun()

    head = st.columns([0.7, 2.4, 1.0, 1.5, 1.5])
    head[0].markdown("**Index**")
    head[1].markdown("**Phone Number**")
    head[2].markdown("**Status**")
    head[3].markdown("**Launch Chat**")
    head[4].markdown("**Mark as Done**")

    rows = fetch_contacts(st.session_state.search_term, st.session_state.status_filter, int(st.session_state.page_size), offset)

    if not rows:
        st.info("No contacts match the current filters.")
    else:
        for idx, row in enumerate(rows, start=offset + 1):
            done_flag = str(row["status"]).lower() == "done"
            cols = st.columns([0.7, 2.4, 1.0, 1.5, 1.5])
            cols[0].markdown(f"**{idx}**")
            cols[1].markdown(phone_html(str(row["phone"]), done_flag), unsafe_allow_html=True)
            cols[2].markdown(status_html(str(row["status"])), unsafe_allow_html=True)
            with cols[3]:
                launch_button(str(row["phone"]), st.session_state.message_template_saved, dimmed=done_flag)
            if cols[4].button("Mark as Done", key=f"row_done_{row['id']}", disabled=done_flag, use_container_width=True):
                mark_done(int(row["id"]))
                st.rerun()
            st.markdown("---")
else:
    st.markdown('<div class="subtle">Table mode is hidden while batch mode is active. Switch the mode in Settings to use the table view.</div>', unsafe_allow_html=True)


st.markdown('<div class="section-title">Export</div>', unsafe_allow_html=True)
completed_df = completed_export_df(st.session_state.search_term)
st.download_button(
    "Export Completed Users CSV",
    data=completed_df.to_csv(index=False).encode("utf-8"),
    file_name="completed_contacts.csv",
    mime="text/csv",
    use_container_width=True,
)
