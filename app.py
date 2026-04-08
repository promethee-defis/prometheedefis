import base64
import html
import mimetypes
import re
from pathlib import Path

import streamlit as st
from supabase import create_client

st.set_page_config(
    page_title="Prométhée — Défis",
    page_icon="🐺",
    layout="centered",
)

# ---------------------------------------------------
# CONFIG
# ---------------------------------------------------
ADMIN_PASSWORD = "Boubouboubou122"

CATEGORIES = ["SOFT", "MOYEN", "DIFFICILE", "HARDCORE", "EXTREME"]
CATEGORY_ORDER = {name: i for i, name in enumerate(CATEGORIES)}

# Couleurs inspirées des ceintures de judo
COLORS = {
    "SOFT": "#F3F1EC",       # blanche
    "MOYEN": "#D7B548",      # jaune
    "DIFFICILE": "#D8893A",  # orange
    "HARDCORE": "#4E8A5C",   # verte
    "EXTREME": "#4870B7",    # bleue
}

CATEGORY_TEXT_COLORS = {
    "SOFT": "#3F352E",
    "MOYEN": "#FFFFFF",
    "DIFFICILE": "#FFFFFF",
    "HARDCORE": "#FFFFFF",
    "EXTREME": "#FFFFFF",
}

COLLAR_LABELS = {
    "SOFT": "Collier blanc",
    "MOYEN": "Collier jaune",
    "DIFFICILE": "Collier orange",
    "HARDCORE": "Collier vert",
    "EXTREME": "Collier bleu",
}

STATUS_LABELS = {
    "todo": "À faire",
    "pending": "En attente de validation",
    "redo": "À refaire",
}

GLOBAL_STATE_KEY = "__GLOBAL__"
GLOBAL_COMPLETED_KEY = "__GLOBAL_COMPLETED__"

# ---------------------------------------------------
# SUPABASE
# ---------------------------------------------------
supabase = create_client(
    st.secrets["SUPABASE_URL"],
    st.secrets["SUPABASE_KEY"],
)

# ---------------------------------------------------
# SESSION
# ---------------------------------------------------
if "logged_profile_slug" not in st.session_state:
    st.session_state.logged_profile_slug = None

if "admin_ok" not in st.session_state:
    st.session_state.admin_ok = False


# ---------------------------------------------------
# UTILS
# ---------------------------------------------------
def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "profil"


def short_text(text: str, limit: int = 90) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def html_text(text: str) -> str:
    return html.escape(str(text))


def html_multiline(text: str) -> str:
    return html.escape(str(text)).replace("\n", "<br>")


def get_profiles():
    data = supabase.table("profiles").select("*").order("name").execute().data
    return data or []


def get_profiles_map():
    profiles = get_profiles()
    return {p["slug"]: p for p in profiles}


def get_challenges(category=None):
    query = supabase.table("challenges").select("*")
    if category:
        query = query.eq("category", category).order("sort_order")
        data = query.execute().data
        return data or []

    data = query.execute().data or []
    data = sorted(
        data,
        key=lambda x: (
            CATEGORY_ORDER.get(x["category"], 999),
            x.get("sort_order", 999999),
            x.get("id", 999999),
        ),
    )
    return data


def get_challenges_map():
    return {category: get_challenges(category) for category in CATEGORIES}


def get_meta_progress_row(profile_slug: str, key: str, default_index: int, default_status: str):
    data = (
        supabase.table("progress")
        .select("*")
        .eq("profile_slug", profile_slug)
        .eq("category", key)
        .order("id")
        .limit(1)
        .execute()
        .data
    )

    if data:
        return data[0]

    row = {
        "profile_slug": profile_slug,
        "category": key,
        "challenge_index": default_index,
        "status": default_status,
    }
    supabase.table("progress").insert(row).execute()
    return row


def set_meta_progress_row(profile_slug: str, key: str, challenge_index: int, status: str):
    existing = (
        supabase.table("progress")
        .select("id")
        .eq("profile_slug", profile_slug)
        .eq("category", key)
        .order("id")
        .limit(1)
        .execute()
        .data
    )

    if existing:
        row_id = existing[0]["id"]
        (
            supabase.table("progress")
            .update(
                {
                    "challenge_index": challenge_index,
                    "status": status,
                }
            )
            .eq("id", row_id)
            .execute()
        )
    else:
        supabase.table("progress").insert(
            {
                "profile_slug": profile_slug,
                "category": key,
                "challenge_index": challenge_index,
                "status": status,
            }
        ).execute()


def get_global_state(profile_slug: str):
    return get_meta_progress_row(profile_slug, GLOBAL_STATE_KEY, 0, "todo")


def set_global_state(profile_slug: str, challenge_index: int, status: str):
    set_meta_progress_row(profile_slug, GLOBAL_STATE_KEY, challenge_index, status)


def get_completed_count(profile_slug: str) -> int:
    row = get_meta_progress_row(profile_slug, GLOBAL_COMPLETED_KEY, 0, "count")
    return int(row["challenge_index"])


def set_completed_count(profile_slug: str, value: int):
    set_meta_progress_row(profile_slug, GLOBAL_COMPLETED_KEY, int(value), "count")


def update_jokers(profile_slug: str, jokers: int):
    supabase.table("profiles").update({"jokers": int(jokers)}).eq("slug", profile_slug).execute()


def current_challenge(profile_slug: str):
    progress = get_global_state(profile_slug)
    items = get_challenges()
    idx = int(progress["challenge_index"])

    if idx >= len(items):
        return None, progress, items

    return items[idx], progress, items


def add_profile(name: str, pin: str, jokers: int):
    slug = slugify(name)
    existing = supabase.table("profiles").select("slug").eq("slug", slug).execute().data or []
    if existing:
        return False, "Ce profil existe déjà."

    supabase.table("profiles").insert(
        {
            "slug": slug,
            "name": name.strip(),
            "pin": pin.strip(),
            "jokers": int(jokers),
        }
    ).execute()

    set_global_state(slug, 0, "todo")
    set_completed_count(slug, 0)

    return True, "Profil créé."


def update_profile(slug: str, name: str, pin: str, jokers: int):
    supabase.table("profiles").update(
        {
            "name": name.strip(),
            "pin": pin.strip(),
            "jokers": int(jokers),
        }
    ).eq("slug", slug).execute()


def delete_profile(slug: str):
    supabase.table("progress").delete().eq("profile_slug", slug).execute()
    supabase.table("profiles").delete().eq("slug", slug).execute()

    if st.session_state.logged_profile_slug == slug:
        st.session_state.logged_profile_slug = None


def add_challenge(category: str, text: str):
    items = get_challenges(category)
    next_order = len(items) + 1
    supabase.table("challenges").insert(
        {
            "category": category,
            "sort_order": next_order,
            "text": text.strip(),
        }
    ).execute()


def update_challenge(challenge_id: int, text: str):
    supabase.table("challenges").update({"text": text.strip()}).eq("id", challenge_id).execute()


def delete_challenge(challenge_id: int, category: str):
    supabase.table("challenges").delete().eq("id", challenge_id).execute()
    normalize_sort_order(category)


def normalize_sort_order(category: str):
    items = get_challenges(category)
    for i, item in enumerate(items, start=1):
        if item["sort_order"] != i:
            supabase.table("challenges").update({"sort_order": i}).eq("id", item["id"]).execute()


def swap_challenge_order(category: str, challenge_id: int, direction: str):
    items = get_challenges(category)
    ids = [item["id"] for item in items]

    if challenge_id not in ids:
        return

    idx = ids.index(challenge_id)

    if direction == "up" and idx > 0:
        a = items[idx - 1]
        b = items[idx]
    elif direction == "down" and idx < len(items) - 1:
        a = items[idx]
        b = items[idx + 1]
    else:
        return

    supabase.table("challenges").update({"sort_order": b["sort_order"]}).eq("id", a["id"]).execute()
    supabase.table("challenges").update({"sort_order": a["sort_order"]}).eq("id", b["id"]).execute()


def find_profile_by_login_input(raw_value: str, profiles: list):
    value = raw_value.strip().lower()
    if not value:
        return None

    for profile in profiles:
        if profile["name"].strip().lower() == value:
            return profile

    for profile in profiles:
        if profile["slug"].strip().lower() == value:
            return profile

    return None


def get_logo_data_uri():
    possible_paths = [Path("logo.jpg"), Path("assets/logo.jpg")]
    logo_path = None

    for p in possible_paths:
        if p.exists():
            logo_path = p
            break

    if logo_path is None:
        return None

    mime_type, _ = mimetypes.guess_type(str(logo_path))
    if mime_type is None:
        mime_type = "image/jpeg"

    data = base64.b64encode(logo_path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{data}"


def get_stage_category(items, idx: int):
    if not items:
        return "SOFT"
    if idx < len(items):
        return items[idx]["category"]
    return items[-1]["category"]


def build_master_list(items, current_idx: int, status: str) -> str:
    rows = ['<div class="challenge-progress-list">']

    for i, item in enumerate(items):
        category = item["category"]
        badge_bg = COLORS.get(category, "#D7C6B3")
        badge_text = CATEGORY_TEXT_COLORS.get(category, "#FFFFFF")

        if i < current_idx:
            row_class = "done"
            icon = "✓"
            text_html = html_multiline(item["text"])
        elif i == current_idx:
            if status == "redo":
                row_class = "redo"
            elif status == "pending":
                row_class = "pending"
            else:
                row_class = "current"
            icon = str(i + 1)
            text_html = html_multiline(item["text"])
        else:
            row_class = "locked"
            icon = "•"
            text_html = "Défi verrouillé — contenu masqué"

        rows.append(
            (
                f'<div class="challenge-progress-row {row_class}">'
                f'<div class="challenge-progress-index">{icon}</div>'
                f'<div class="challenge-progress-category" style="background:{badge_bg}; color:{badge_text};">{html_text(category)}</div>'
                f'<div class="challenge-progress-text">{text_html}</div>'
                '</div>'
            )
        )

    rows.append("</div>")
    return "".join(rows)


# ---------------------------------------------------
# STYLE
# ---------------------------------------------------
@import url('https://fonts.googleapis.com/css2?family=Lato:wght@300;400;700;900&display=swap');

html, body, [class*="css"], [data-testid="stAppViewContainer"], [data-testid="stMarkdownContainer"] {
    font-family: 'Lato', sans-serif !important;
}

.stApp {
    background:
        radial-gradient(circle at top, rgba(140, 38, 65, 0.06), transparent 28%),
        linear-gradient(180deg, #FFFFFF 0%, #FBF8F4 100%);
}

.block-container {
    max-width: 940px;
    padding-top: 1rem;
    padding-bottom: 2rem;
}

h1, h2, h3, h4, h5, h6,
p, label, div, span {
    color: #1D1D1D;
    font-family: 'Lato', sans-serif !important;
}

.hero-wrap {
    text-align: center;
    padding: 0.2rem 0 1.2rem 0;
}

.hero-logo-band {
    width: 100%;
    background: linear-gradient(180deg, rgba(255,255,255,0.97), rgba(255,255,255,0.88));
    border: 1px solid rgba(167, 132, 99, 0.10);
    border-radius: 22px;
    padding: 1rem 0 0.8rem 0;
    margin: 0 auto 1rem auto;
    box-shadow: 0 10px 24px rgba(30, 20, 10, 0.03);
}

.hero-logo-img {
    display: block;
    margin: 0 auto;
    max-width: 120px;
    width: 120px;
    height: auto;
    mix-blend-mode: multiply;
}

.hero-kicker {
    color: #9A6A4B;
    text-transform: uppercase;
    letter-spacing: 0.22em;
    font-size: 0.78rem;
    margin-top: 0.15rem;
    margin-bottom: 0.45rem;
    font-weight: 400;
}

.hero-title {
    font-size: 2.25rem;
    font-weight: 900;
    color: #181818;
    margin-bottom: 0.15rem;
}

.hero-subtitle {
    color: #6B6258;
    font-size: 0.98rem;
    margin-bottom: 0.75rem;
    font-weight: 400;
}

.hero-line {
    width: 170px;
    height: 1px;
    margin: 0 auto;
    background: linear-gradient(90deg, transparent, #B79372, transparent);
}

.panel-box {
    background: rgba(255,255,255,0.82);
    border: 1px solid rgba(167, 132, 99, 0.18);
    border-radius: 18px;
    padding: 0.95rem 1rem;
    margin-bottom: 1rem;
    box-shadow: 0 12px 28px rgba(30, 20, 10, 0.05);
}

.panel-title {
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.16em;
    color: #A06F4A;
    margin-bottom: 0.28rem;
}

.panel-value {
    color: #1B1B1B;
    font-size: 1.02rem;
    font-weight: 700;
}

.subtle-text {
    color: #6A625A;
    font-size: 0.92rem;
}

.collar-chip {
    display: inline-block;
    margin-top: 0.55rem;
    padding: 0.38rem 0.85rem;
    border-radius: 999px;
    font-size: 0.82rem;
    font-weight: 900;
    border: 1px solid rgba(0,0,0,0.08);
}

.current-card {
    background: rgba(255,255,255,0.88);
    border: 1px solid rgba(167, 132, 99, 0.18);
    border-radius: 20px;
    padding: 1rem;
    box-shadow: 0 12px 28px rgba(30, 20, 10, 0.05);
    height: 100%;
}

.current-card-top {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    flex-wrap: wrap;
    margin-bottom: 0.75rem;
}

.current-card-title {
    font-size: 1.02rem;
    font-weight: 900;
    color: #1B1B1B;
}

.current-card-sub {
    color: #6B6258;
    font-size: 0.92rem;
    font-weight: 700;
}

.current-category-chip {
    display: inline-block;
    padding: 0.34rem 0.72rem;
    border-radius: 999px;
    font-size: 0.74rem;
    font-weight: 900;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}

.current-card-text {
    font-size: 1.04rem;
    line-height: 1.68;
    color: #1E1E1E;
}

.status-chip {
    display: inline-block;
    margin-top: 0.75rem;
    padding: 0.42rem 0.9rem;
    border-radius: 999px;
    background: #F3EEE8;
    border: 1px solid rgba(140, 110, 80, 0.12);
    color: #5A4A3B;
    font-size: 0.84rem;
    font-weight: 700;
}

.challenge-shell {
    background: rgba(255,255,255,0.84);
    border: 1px solid rgba(167, 132, 99, 0.16);
    border-radius: 22px;
    padding: 1rem;
    margin-bottom: 0.55rem;
    box-shadow: 0 12px 28px rgba(30, 20, 10, 0.05);
}

.list-title {
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.16em;
    color: #A06F4A;
    margin-bottom: 0.8rem;
    font-weight: 900;
}

.challenge-progress-list {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
}

.challenge-progress-row {
    border-radius: 14px;
    padding: 0.72rem 0.85rem;
    border: 1px solid rgba(167, 132, 99, 0.14);
    background: rgba(255,255,255,0.78);
    display: flex;
    align-items: flex-start;
    gap: 0.65rem;
}

.challenge-progress-index {
    min-width: 30px;
    width: 30px;
    height: 30px;
    border-radius: 999px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.82rem;
    font-weight: 900;
    background: #F3EEE8;
    color: #5A4A3B;
    border: 1px solid rgba(140, 110, 80, 0.10);
    flex-shrink: 0;
}

.challenge-progress-category {
    min-width: 88px;
    padding: 0.34rem 0.6rem;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 900;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    text-align: center;
    flex-shrink: 0;
    margin-top: 1px;
}

.challenge-progress-text {
    flex: 1;
    font-size: 0.96rem;
    line-height: 1.55;
    color: #2A2A2A;
    word-break: break-word;
}

.challenge-progress-row.done {
    background: rgba(142, 163, 143, 0.12);
    border-color: rgba(142, 163, 143, 0.22);
}

.challenge-progress-row.done .challenge-progress-index {
    background: #8EA38F;
    color: #FFFFFF;
    border-color: #8EA38F;
}

.challenge-progress-row.current {
    background: rgba(255,255,255,0.98);
    border-color: rgba(167, 132, 99, 0.24);
    box-shadow: 0 8px 20px rgba(30, 20, 10, 0.04);
}

.challenge-progress-row.current .challenge-progress-index {
    background: #2E0F13;
    color: #FFFFFF;
    border-color: #2E0F13;
}

.challenge-progress-row.pending {
    background: rgba(216, 184, 129, 0.14);
    border-color: rgba(216, 184, 129, 0.24);
}

.challenge-progress-row.pending .challenge-progress-index {
    background: #B6925E;
    color: #FFFFFF;
    border-color: #B6925E;
}

.challenge-progress-row.locked {
    background: rgba(255,255,255,0.62);
    border-color: rgba(167, 132, 99, 0.10);
}

.challenge-progress-row.locked .challenge-progress-text {
    filter: blur(4px);
    opacity: 0.82;
    user-select: none;
    pointer-events: none;
}

.challenge-progress-row.locked .challenge-progress-index {
    background: #E9E2D9;
    color: #8B7E71;
}

.challenge-progress-row.redo {
    background: rgba(162, 74, 94, 0.08);
    border-color: rgba(162, 74, 94, 0.18);
}

.challenge-progress-row.redo .challenge-progress-index {
    background: #A24A5E;
    color: #FFFFFF;
    border-color: #A24A5E;
}

.compact-row {
    background: rgba(255,255,255,0.88);
    border: 1px solid rgba(167, 132, 99, 0.16);
    border-radius: 14px;
    padding: 0.7rem 0.85rem 0.45rem 0.85rem;
    margin-bottom: 0.65rem;
}

.compact-top {
    font-size: 0.84rem;
    color: #7A6B5D;
    margin-bottom: 0.25rem;
}

.compact-main {
    font-size: 0.96rem;
    font-weight: 700;
    color: #1E1E1E;
    margin-bottom: 0.45rem;
}

.stButton > button {
    width: 100%;
    border-radius: 999px;
    border: 1px solid #2E0F13 !important;
    background: #2E0F13 !important;
    color: #FFFFFF !important;
    min-height: 2.1rem;
    font-weight: 700;
    font-size: 0.9rem;
    padding: 0.34rem 0.85rem;
    box-shadow: 0 6px 14px rgba(46, 15, 19, 0.18);
}

.stButton > button * {
    color: #FFFFFF !important;
    fill: #FFFFFF !important;
}

.stButton > button:hover {
    border-color: #3A1419 !important;
    background: #3A1419 !important;
    color: #FFFFFF !important;
}

.stButton > button:hover * {
    color: #FFFFFF !important;
    fill: #FFFFFF !important;
}

.stTextInput > div > div > input,
.stTextArea textarea,
.stSelectbox div[data-baseweb="select"] > div,
.stNumberInput input {
    background: rgba(255,255,255,0.95) !important;
    border-radius: 12px !important;
    color: #1D1D1D !important;
    font-family: 'Lato', sans-serif !important;
    border: 1px solid rgba(167, 132, 99, 0.22) !important;
}

.stSelectbox div[data-baseweb="select"] span,
.stSelectbox div[data-baseweb="select"] div {
    color: #1D1D1D !important;
}

/* Menu déroulant selectbox */
div[data-baseweb="popover"] {
    background: #FFFFFF !important;
    border-radius: 14px !important;
    border: 1px solid rgba(167, 132, 99, 0.18) !important;
    box-shadow: 0 12px 28px rgba(30, 20, 10, 0.10) !important;
}

div[data-baseweb="popover"] ul,
div[data-baseweb="popover"] [role="listbox"] {
    background: #FFFFFF !important;
}

div[data-baseweb="popover"] [role="option"] {
    background: #FFFFFF !important;
    color: #1D1D1D !important;
}

div[data-baseweb="popover"] [role="option"] * {
    color: #1D1D1D !important;
}

div[data-baseweb="popover"] [role="option"]:hover {
    background: #F5EFE8 !important;
    color: #1D1D1D !important;
}

div[data-baseweb="popover"] [role="option"][aria-selected="true"] {
    background: #EFE5DA !important;
    color: #1D1D1D !important;
}

div[data-baseweb="popover"] [role="option"][aria-selected="true"] * {
    color: #1D1D1D !important;
}

.stTabs [data-baseweb="tab"] {
    color: #6C625A;
    font-family: 'Lato', sans-serif !important;
}

.stTabs [aria-selected="true"] {
    color: #1C1C1C !important;
}

.stRadio label {
    color: #1D1D1D !important;
    font-family: 'Lato', sans-serif !important;
}

@media (max-width: 768px) {
    .block-container {
        padding-top: 0.7rem;
        padding-bottom: 1.6rem;
    }

    .hero-logo-img {
        max-width: 98px;
        width: 98px;
    }

    .hero-title {
        font-size: 1.95rem;
    }

    .hero-subtitle {
        font-size: 0.92rem;
    }

    .current-card,
    .panel-box,
    .challenge-shell {
        padding: 0.85rem;
    }

    .challenge-progress-row {
        padding: 0.66rem 0.72rem;
        gap: 0.55rem;
    }

    .challenge-progress-category {
        min-width: 76px;
        font-size: 0.68rem;
        padding: 0.32rem 0.5rem;
    }

    .challenge-progress-text {
        font-size: 0.92rem;
    }

    .stButton > button {
        min-height: 2rem;
        font-size: 0.86rem;
    }
}
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------
# UI
# ---------------------------------------------------
def show_header():
    logo_data_uri = get_logo_data_uri()

    logo_html = ""
    if logo_data_uri is not None:
        logo_html = (
            '<div class="hero-logo-band">'
            f'<img src="{logo_data_uri}" class="hero-logo-img" alt="Logo">'
            '</div>'
        )

    header_html = (
        '<div class="hero-wrap">'
        f'{logo_html}'
        '<div class="hero-kicker">PROMÉTHÉE</div>'
        '<div class="hero-title">Défis</div>'
        '<div class="hero-subtitle">Servir par le jeu</div>'
        '<div class="hero-line"></div>'
        '</div>'
    )

    st.markdown(header_html, unsafe_allow_html=True)


def render_current_challenge(profile: dict, current_item, progress, items, completed_count: int):
    current_category = get_stage_category(items, int(progress["challenge_index"]))
    collar_label = COLLAR_LABELS[current_category]
    collar_bg = COLORS[current_category]
    collar_text = CATEGORY_TEXT_COLORS[current_category]

    profile_html = (
        '<div class="panel-box">'
        '<div class="panel-title">Profil</div>'
        f'<div class="panel-value">{html_text(profile["name"])}</div>'
        f'<div class="subtle-text">Jokers restants : {int(profile["jokers"])}</div>'
        f'<div class="subtle-text">Défis achevés : {completed_count}</div>'
        f'<div class="collar-chip" style="background:{collar_bg}; color:{collar_text};">{html_text(collar_label)}</div>'
        '</div>'
    )

    c_profile, c_current, c_done, c_joker = st.columns([2.2, 4.5, 1.4, 1.4], gap="small")

    with c_profile:
        st.markdown(profile_html, unsafe_allow_html=True)
        if st.button("Se déconnecter", use_container_width=True):
            st.session_state.logged_profile_slug = None
            st.rerun()

    if current_item is None:
        current_html = (
            '<div class="current-card">'
            '<div class="current-card-title">Parcours terminé</div>'
            '<div class="current-card-sub">Tous les défis visibles sont franchis.</div>'
            '<div class="status-chip">Terminé</div>'
            '</div>'
        )
        with c_current:
            st.markdown(current_html, unsafe_allow_html=True)
        with c_done:
            st.empty()
        with c_joker:
            st.empty()
        return

    category = current_item["category"]
    chip_bg = COLORS[category]
    chip_text = CATEGORY_TEXT_COLORS[category]
    status_label = STATUS_LABELS.get(progress["status"], "À faire")

    current_html = (
        '<div class="current-card">'
        '<div class="current-card-top">'
        f'<div class="current-category-chip" style="background:{chip_bg}; color:{chip_text};">{html_text(category)}</div>'
        '<div class="current-card-title">Défi en cours</div>'
        '</div>'
        f'<div class="current-card-sub">Défi {int(progress["challenge_index"]) + 1} sur {len(items)}</div>'
        f'<div class="current-card-text">{html_multiline(current_item["text"])}</div>'
        f'<div class="status-chip">Statut : {html_text(status_label)}</div>'
        '</div>'
    )

    with c_current:
        st.markdown(current_html, unsafe_allow_html=True)

    with c_done:
        st.markdown("<div style='height:0.2rem;'></div>", unsafe_allow_html=True)
        if progress["status"] in ["todo", "redo"]:
            if st.button("✓ Fait", key=f"done_{profile['slug']}", use_container_width=True):
                set_global_state(profile["slug"], int(progress["challenge_index"]), "pending")
                st.rerun()
        else:
            st.empty()

    with c_joker:
        st.markdown("<div style='height:0.2rem;'></div>", unsafe_allow_html=True)
        if progress["status"] in ["todo", "redo"]:
            disabled = int(profile["jokers"]) <= 0
            if st.button("✦ Joker", key=f"joker_{profile['slug']}", use_container_width=True, disabled=disabled):
                update_jokers(profile["slug"], max(0, int(profile["jokers"]) - 1))
                set_global_state(profile["slug"], int(progress["challenge_index"]) + 1, "todo")
                st.rerun()
        else:
            st.empty()


def render_master_list(items, progress):
    title_html = (
        '<div class="challenge-shell">'
        '<div class="list-title">Parcours complet</div>'
        f'{build_master_list(items, int(progress["challenge_index"]), progress["status"])}'
        '</div>'
    )
    st.markdown(title_html, unsafe_allow_html=True)


def render_user_area():
    st.subheader("Espace personnel")

    profiles = get_profiles()
    if not profiles:
        st.warning("Aucun profil.")
        return

    profiles_map = {p["slug"]: p for p in profiles}

    if (
        st.session_state.logged_profile_slug is not None
        and st.session_state.logged_profile_slug not in profiles_map
    ):
        st.session_state.logged_profile_slug = None

    if st.session_state.logged_profile_slug is None:
        pseudo = st.text_input("Pseudo")
        pin = st.text_input("Code PIN", type="password")

        if st.button("Entrer", use_container_width=True):
            profile = find_profile_by_login_input(pseudo, profiles)
            if profile is not None and pin == profile["pin"]:
                st.session_state.logged_profile_slug = profile["slug"]
                st.rerun()
            else:
                st.error("Identifiants incorrects.")
        return

    profile = profiles_map[st.session_state.logged_profile_slug]
    current_item, progress, items = current_challenge(profile["slug"])
    completed_count = get_completed_count(profile["slug"])

    render_current_challenge(profile, current_item, progress, items, completed_count)
    st.markdown("<div style='height:0.45rem;'></div>", unsafe_allow_html=True)
    render_master_list(items, progress)


def render_admin_area():
    st.subheader("Espace admin")

    if not st.session_state.admin_ok:
        password = st.text_input("Mot de passe admin", type="password")
        if st.button("Connexion admin", use_container_width=True):
            if password == ADMIN_PASSWORD:
                st.session_state.admin_ok = True
                st.rerun()
            else:
                st.error("Mot de passe incorrect.")
        return

    top1, _ = st.columns([1, 4])
    with top1:
        if st.button("Quitter", use_container_width=True):
            st.session_state.admin_ok = False
            st.rerun()

    tab1, tab2, tab3 = st.tabs(["Validations", "Défis", "Profils"])

    with tab1:
        profiles = get_profiles()
        profiles_map = {p["slug"]: p for p in profiles}
        all_challenges = get_challenges()

        pending_items = []
        for profile in profiles:
            global_state = get_global_state(profile["slug"])
            idx = int(global_state["challenge_index"])
            if global_state["status"] == "pending" and idx < len(all_challenges):
                current_item = all_challenges[idx]
                pending_items.append(
                    {
                        "profile_slug": profile["slug"],
                        "profile_name": profile["name"],
                        "category": current_item["category"],
                        "challenge_index": idx,
                        "text": current_item["text"],
                    }
                )

        summary_html = (
            '<div class="panel-box">'
            '<div class="panel-title">En attente</div>'
            f'<div class="panel-value">{len(pending_items)}</div>'
            '</div>'
        )
        st.markdown(summary_html, unsafe_allow_html=True)

        if not pending_items:
            st.info("Aucun défi en attente.")
        else:
            profile_names = sorted(list({item["profile_name"] for item in pending_items}))
            filter_profile = st.selectbox("Filtrer par profil", ["Tous"] + profile_names)
            filter_category = st.selectbox("Filtrer par catégorie", ["Toutes"] + CATEGORIES)

            for item in pending_items:
                if filter_profile != "Tous" and item["profile_name"] != filter_profile:
                    continue
                if filter_category != "Toutes" and item["category"] != filter_category:
                    continue

                row_html = (
                    '<div class="compact-row">'
                    f'<div class="compact-top">{html_text(item["profile_name"])} • {html_text(item["category"])}</div>'
                    f'<div class="compact-main">{html_text(item["text"])}</div>'
                    '</div>'
                )
                st.markdown(row_html, unsafe_allow_html=True)

                c1, c2 = st.columns(2)
                with c1:
                    if st.button(
                        "Valider",
                        key=f"approve_{item['profile_slug']}",
                        use_container_width=True,
                    ):
                        completed_count = get_completed_count(item["profile_slug"]) + 1
                        set_completed_count(item["profile_slug"], completed_count)
                        set_global_state(
                            item["profile_slug"],
                            item["challenge_index"] + 1,
                            "todo",
                        )

                        if completed_count % 10 == 0:
                            current_jokers = int(profiles_map[item["profile_slug"]]["jokers"])
                            update_jokers(item["profile_slug"], current_jokers + 1)

                        st.rerun()

                with c2:
                    if st.button(
                        "À refaire",
                        key=f"redo_{item['profile_slug']}",
                        use_container_width=True,
                    ):
                        set_global_state(
                            item["profile_slug"],
                            item["challenge_index"],
                            "redo",
                        )
                        st.rerun()

    with tab2:
        category = st.selectbox("Catégorie", CATEGORIES, key="admin_category")
        items = get_challenges(category)

        count_html = (
            '<div class="panel-box">'
            '<div class="panel-title">Nombre de défis</div>'
            f'<div class="panel-value">{len(items)}</div>'
            '</div>'
        )
        st.markdown(count_html, unsafe_allow_html=True)

        st.markdown("### Ajouter un défi")
        new_challenge = st.text_area("Texte", key=f"new_{category}", height=120)
        if st.button("Ajouter", key=f"add_{category}", use_container_width=True):
            if new_challenge.strip():
                add_challenge(category, new_challenge)
                st.rerun()
            else:
                st.error("Le texte est vide.")

        st.markdown("### Modifier un défi existant")

        if not items:
            st.info("Aucun défi dans cette catégorie.")
        else:
            selected_id = st.selectbox(
                "Défi",
                options=[item["id"] for item in items],
                format_func=lambda challenge_id: next(
                    f"{i + 1}. {short_text(item['text'], 80)}"
                    for i, item in enumerate(items)
                    if item["id"] == challenge_id
                ),
                key=f"selected_{category}",
            )

            selected_item = next(item for item in items if item["id"] == selected_id)

            edited_text = st.text_area(
                "Texte du défi",
                value=selected_item["text"],
                key=f"edit_text_{category}_{selected_id}",
                height=180,
            )

            c1, c2 = st.columns(2)
            with c1:
                if st.button("Enregistrer", key=f"save_{category}", use_container_width=True):
                    update_challenge(selected_item["id"], edited_text)
                    st.rerun()
            with c2:
                if st.button("Supprimer", key=f"delete_{category}", use_container_width=True):
                    delete_challenge(selected_item["id"], category)
                    st.rerun()

            c3, c4 = st.columns(2)
            with c3:
                if st.button("Monter", key=f"up_{category}", use_container_width=True):
                    swap_challenge_order(category, selected_item["id"], "up")
                    st.rerun()
            with c4:
                if st.button("Descendre", key=f"down_{category}", use_container_width=True):
                    swap_challenge_order(category, selected_item["id"], "down")
                    st.rerun()

    with tab3:
        st.markdown("### Ajouter un profil")
        with st.form("new_profile_form"):
            new_name = st.text_input("Pseudo affiché")
            new_pin = st.text_input("PIN")
            new_jokers = st.number_input("Jokers", min_value=0, max_value=99, value=3, step=1)
            submitted = st.form_submit_button("Créer")

            if submitted:
                if not new_name.strip() or not new_pin.strip():
                    st.error("Pseudo et PIN obligatoires.")
                else:
                    ok, message = add_profile(new_name, new_pin, int(new_jokers))
                    if ok:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)

        st.markdown("### Modifier un profil")
        profiles = get_profiles()
        if not profiles:
            st.info("Aucun profil.")
        else:
            selected_profile_slug = st.selectbox(
                "Profil",
                options=[p["slug"] for p in profiles],
                format_func=lambda slug: next(p["name"] for p in profiles if p["slug"] == slug),
                key="profile_to_edit",
            )

            profile = next(p for p in profiles if p["slug"] == selected_profile_slug)

            updated_name = st.text_input("Pseudo", value=profile["name"], key=f"name_{selected_profile_slug}")
            updated_pin = st.text_input("PIN", value=profile["pin"], key=f"pin_{selected_profile_slug}")
            updated_jokers = st.number_input(
                "Jokers",
                min_value=0,
                max_value=99,
                value=int(profile["jokers"]),
                step=1,
                key=f"jokers_{selected_profile_slug}",
            )

            c1, c2 = st.columns(2)
            with c1:
                if st.button("Mettre à jour", key=f"save_profile_{selected_profile_slug}", use_container_width=True):
                    update_profile(selected_profile_slug, updated_name, updated_pin, int(updated_jokers))
                    st.rerun()

            with c2:
                if st.button(
                    "Supprimer le profil",
                    key=f"delete_profile_{selected_profile_slug}",
                    use_container_width=True,
                ):
                    delete_profile(selected_profile_slug)
                    st.rerun()


# ---------------------------------------------------
# APP
# ---------------------------------------------------
show_header()
mode = st.radio("Choisir un espace", ["Personnel", "Admin"], horizontal=True)

if mode == "Personnel":
    render_user_area()
else:
    render_admin_area()
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------
# UI
# ---------------------------------------------------
def show_header():
    logo_data_uri = get_logo_data_uri()

    logo_html = ""
    if logo_data_uri is not None:
        logo_html = (
            '<div class="hero-logo-band">'
            f'<img src="{logo_data_uri}" class="hero-logo-img" alt="Logo">'
            '</div>'
        )

    header_html = (
        '<div class="hero-wrap">'
        f'{logo_html}'
        '<div class="hero-kicker">PROMÉTHÉE</div>'
        '<div class="hero-title">Défis</div>'
        '<div class="hero-subtitle">Servir par le jeu</div>'
        '<div class="hero-line"></div>'
        '</div>'
    )

    st.markdown(header_html, unsafe_allow_html=True)


def render_current_challenge(profile: dict, current_item, progress, items, completed_count: int):
    current_category = get_stage_category(items, int(progress["challenge_index"]))
    collar_label = COLLAR_LABELS[current_category]
    collar_bg = COLORS[current_category]
    collar_text = CATEGORY_TEXT_COLORS[current_category]

    profile_html = (
        '<div class="panel-box">'
        '<div class="panel-title">Profil</div>'
        f'<div class="panel-value">{html_text(profile["name"])}</div>'
        f'<div class="subtle-text">Jokers restants : {int(profile["jokers"])}</div>'
        f'<div class="subtle-text">Défis achevés : {completed_count}</div>'
        f'<div class="collar-chip" style="background:{collar_bg}; color:{collar_text};">{html_text(collar_label)}</div>'
        '</div>'
    )

    c_profile, c_current, c_done, c_joker = st.columns([2.2, 4.5, 1.4, 1.4], gap="small")

    with c_profile:
        st.markdown(profile_html, unsafe_allow_html=True)
        if st.button("Se déconnecter", use_container_width=True):
            st.session_state.logged_profile_slug = None
            st.rerun()

    if current_item is None:
        current_html = (
            '<div class="current-card">'
            '<div class="current-card-title">Parcours terminé</div>'
            '<div class="current-card-sub">Tous les défis visibles sont franchis.</div>'
            '<div class="status-chip">Terminé</div>'
            '</div>'
        )
        with c_current:
            st.markdown(current_html, unsafe_allow_html=True)
        with c_done:
            st.empty()
        with c_joker:
            st.empty()
        return

    category = current_item["category"]
    chip_bg = COLORS[category]
    chip_text = CATEGORY_TEXT_COLORS[category]
    status_label = STATUS_LABELS.get(progress["status"], "À faire")

    current_html = (
        '<div class="current-card">'
        '<div class="current-card-top">'
        f'<div class="current-category-chip" style="background:{chip_bg}; color:{chip_text};">{html_text(category)}</div>'
        '<div class="current-card-title">Défi en cours</div>'
        '</div>'
        f'<div class="current-card-sub">Défi {int(progress["challenge_index"]) + 1} sur {len(items)}</div>'
        f'<div class="current-card-text">{html_multiline(current_item["text"])}</div>'
        f'<div class="status-chip">Statut : {html_text(status_label)}</div>'
        '</div>'
    )

    with c_current:
        st.markdown(current_html, unsafe_allow_html=True)

    with c_done:
        st.markdown("<div style='height:0.2rem;'></div>", unsafe_allow_html=True)
        if progress["status"] in ["todo", "redo"]:
            if st.button("✓ Fait", key=f"done_{profile['slug']}", use_container_width=True):
                set_global_state(profile["slug"], int(progress["challenge_index"]), "pending")
                st.rerun()
        else:
            st.empty()

    with c_joker:
        st.markdown("<div style='height:0.2rem;'></div>", unsafe_allow_html=True)
        if progress["status"] in ["todo", "redo"]:
            disabled = int(profile["jokers"]) <= 0
            if st.button("✦ Joker", key=f"joker_{profile['slug']}", use_container_width=True, disabled=disabled):
                update_jokers(profile["slug"], max(0, int(profile["jokers"]) - 1))
                set_global_state(profile["slug"], int(progress["challenge_index"]) + 1, "todo")
                st.rerun()
        else:
            st.empty()


def render_master_list(items, progress):
    title_html = (
        '<div class="challenge-shell">'
        '<div class="list-title">Parcours complet</div>'
        f'{build_master_list(items, int(progress["challenge_index"]), progress["status"])}'
        '</div>'
    )
    st.markdown(title_html, unsafe_allow_html=True)


def render_user_area():
    st.subheader("Espace personnel")

    profiles = get_profiles()
    if not profiles:
        st.warning("Aucun profil.")
        return

    profiles_map = {p["slug"]: p for p in profiles}

    if (
        st.session_state.logged_profile_slug is not None
        and st.session_state.logged_profile_slug not in profiles_map
    ):
        st.session_state.logged_profile_slug = None

    if st.session_state.logged_profile_slug is None:
        pseudo = st.text_input("Pseudo")
        pin = st.text_input("Code PIN", type="password")

        if st.button("Entrer", use_container_width=True):
            profile = find_profile_by_login_input(pseudo, profiles)
            if profile is not None and pin == profile["pin"]:
                st.session_state.logged_profile_slug = profile["slug"]
                st.rerun()
            else:
                st.error("Identifiants incorrects.")
        return

    profile = profiles_map[st.session_state.logged_profile_slug]
    current_item, progress, items = current_challenge(profile["slug"])
    completed_count = get_completed_count(profile["slug"])

    render_current_challenge(profile, current_item, progress, items, completed_count)
    st.markdown("<div style='height:0.45rem;'></div>", unsafe_allow_html=True)
    render_master_list(items, progress)


def render_admin_area():
    st.subheader("Espace admin")

    if not st.session_state.admin_ok:
        password = st.text_input("Mot de passe admin", type="password")
        if st.button("Connexion admin", use_container_width=True):
            if password == ADMIN_PASSWORD:
                st.session_state.admin_ok = True
                st.rerun()
            else:
                st.error("Mot de passe incorrect.")
        return

    top1, _ = st.columns([1, 4])
    with top1:
        if st.button("Quitter", use_container_width=True):
            st.session_state.admin_ok = False
            st.rerun()

    tab1, tab2, tab3 = st.tabs(["Validations", "Défis", "Profils"])

    with tab1:
        profiles = get_profiles()
        profiles_map = {p["slug"]: p for p in profiles}
        all_challenges = get_challenges()

        pending_items = []
        for profile in profiles:
            global_state = get_global_state(profile["slug"])
            idx = int(global_state["challenge_index"])
            if global_state["status"] == "pending" and idx < len(all_challenges):
                current_item = all_challenges[idx]
                pending_items.append(
                    {
                        "profile_slug": profile["slug"],
                        "profile_name": profile["name"],
                        "category": current_item["category"],
                        "challenge_index": idx,
                        "text": current_item["text"],
                    }
                )

        summary_html = (
            '<div class="panel-box">'
            '<div class="panel-title">En attente</div>'
            f'<div class="panel-value">{len(pending_items)}</div>'
            '</div>'
        )
        st.markdown(summary_html, unsafe_allow_html=True)

        if not pending_items:
            st.info("Aucun défi en attente.")
        else:
            profile_names = sorted(list({item["profile_name"] for item in pending_items}))
            filter_profile = st.selectbox("Filtrer par profil", ["Tous"] + profile_names)
            filter_category = st.selectbox("Filtrer par catégorie", ["Toutes"] + CATEGORIES)

            for item in pending_items:
                if filter_profile != "Tous" and item["profile_name"] != filter_profile:
                    continue
                if filter_category != "Toutes" and item["category"] != filter_category:
                    continue

                row_html = (
                    '<div class="compact-row">'
                    f'<div class="compact-top">{html_text(item["profile_name"])} • {html_text(item["category"])}</div>'
                    f'<div class="compact-main">{html_text(item["text"])}</div>'
                    '</div>'
                )
                st.markdown(row_html, unsafe_allow_html=True)

                c1, c2 = st.columns(2)
                with c1:
                    if st.button(
                        "Valider",
                        key=f"approve_{item['profile_slug']}",
                        use_container_width=True,
                    ):
                        completed_count = get_completed_count(item["profile_slug"]) + 1
                        set_completed_count(item["profile_slug"], completed_count)
                        set_global_state(
                            item["profile_slug"],
                            item["challenge_index"] + 1,
                            "todo",
                        )

                        if completed_count % 10 == 0:
                            current_jokers = int(profiles_map[item["profile_slug"]]["jokers"])
                            update_jokers(item["profile_slug"], current_jokers + 1)

                        st.rerun()

                with c2:
                    if st.button(
                        "À refaire",
                        key=f"redo_{item['profile_slug']}",
                        use_container_width=True,
                    ):
                        set_global_state(
                            item["profile_slug"],
                            item["challenge_index"],
                            "redo",
                        )
                        st.rerun()

    with tab2:
        category = st.selectbox("Catégorie", CATEGORIES, key="admin_category")
        items = get_challenges(category)

        count_html = (
            '<div class="panel-box">'
            '<div class="panel-title">Nombre de défis</div>'
            f'<div class="panel-value">{len(items)}</div>'
            '</div>'
        )
        st.markdown(count_html, unsafe_allow_html=True)

        st.markdown("### Ajouter un défi")
        new_challenge = st.text_area("Texte", key=f"new_{category}", height=120)
        if st.button("Ajouter", key=f"add_{category}", use_container_width=True):
            if new_challenge.strip():
                add_challenge(category, new_challenge)
                st.rerun()
            else:
                st.error("Le texte est vide.")

        st.markdown("### Modifier un défi existant")

        if not items:
            st.info("Aucun défi dans cette catégorie.")
        else:
            selected_id = st.selectbox(
                "Défi",
                options=[item["id"] for item in items],
                format_func=lambda challenge_id: next(
                    f"{i + 1}. {short_text(item['text'], 80)}"
                    for i, item in enumerate(items)
                    if item["id"] == challenge_id
                ),
                key=f"selected_{category}",
            )

            selected_item = next(item for item in items if item["id"] == selected_id)

            edited_text = st.text_area(
                "Texte du défi",
                value=selected_item["text"],
                key=f"edit_text_{category}_{selected_id}",
                height=180,
            )

            c1, c2 = st.columns(2)
            with c1:
                if st.button("Enregistrer", key=f"save_{category}", use_container_width=True):
                    update_challenge(selected_item["id"], edited_text)
                    st.rerun()
            with c2:
                if st.button("Supprimer", key=f"delete_{category}", use_container_width=True):
                    delete_challenge(selected_item["id"], category)
                    st.rerun()

            c3, c4 = st.columns(2)
            with c3:
                if st.button("Monter", key=f"up_{category}", use_container_width=True):
                    swap_challenge_order(category, selected_item["id"], "up")
                    st.rerun()
            with c4:
                if st.button("Descendre", key=f"down_{category}", use_container_width=True):
                    swap_challenge_order(category, selected_item["id"], "down")
                    st.rerun()

    with tab3:
        st.markdown("### Ajouter un profil")
        with st.form("new_profile_form"):
            new_name = st.text_input("Pseudo affiché")
            new_pin = st.text_input("PIN")
            new_jokers = st.number_input("Jokers", min_value=0, max_value=99, value=3, step=1)
            submitted = st.form_submit_button("Créer")

            if submitted:
                if not new_name.strip() or not new_pin.strip():
                    st.error("Pseudo et PIN obligatoires.")
                else:
                    ok, message = add_profile(new_name, new_pin, int(new_jokers))
                    if ok:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)

        st.markdown("### Modifier un profil")
        profiles = get_profiles()
        if not profiles:
            st.info("Aucun profil.")
        else:
            selected_profile_slug = st.selectbox(
                "Profil",
                options=[p["slug"] for p in profiles],
                format_func=lambda slug: next(p["name"] for p in profiles if p["slug"] == slug),
                key="profile_to_edit",
            )

            profile = next(p for p in profiles if p["slug"] == selected_profile_slug)

            updated_name = st.text_input("Pseudo", value=profile["name"], key=f"name_{selected_profile_slug}")
            updated_pin = st.text_input("PIN", value=profile["pin"], key=f"pin_{selected_profile_slug}")
            updated_jokers = st.number_input(
                "Jokers",
                min_value=0,
                max_value=99,
                value=int(profile["jokers"]),
                step=1,
                key=f"jokers_{selected_profile_slug}",
            )

            c1, c2 = st.columns(2)
            with c1:
                if st.button("Mettre à jour", key=f"save_profile_{selected_profile_slug}", use_container_width=True):
                    update_profile(selected_profile_slug, updated_name, updated_pin, int(updated_jokers))
                    st.rerun()

            with c2:
                if st.button(
                    "Supprimer le profil",
                    key=f"delete_profile_{selected_profile_slug}",
                    use_container_width=True,
                ):
                    delete_profile(selected_profile_slug)
                    st.rerun()


# ---------------------------------------------------
# APP
# ---------------------------------------------------
show_header()
mode = st.radio("Choisir un espace", ["Personnel", "Admin"], horizontal=True)

if mode == "Personnel":
    render_user_area()
else:
    render_admin_area()
