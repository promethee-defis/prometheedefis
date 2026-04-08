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

COLORS = {
    "SOFT": "#8EA38F",
    "MOYEN": "#B6925E",
    "DIFFICILE": "#B37455",
    "HARDCORE": "#A24A5E",
    "EXTREME": "#7B2F45",
}

STATUS_LABELS = {
    "todo": "À faire",
    "pending": "En attente",
    "redo": "À refaire",
}

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
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def html_text(text: str) -> str:
    return html.escape(text)


def html_multiline(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def get_profiles():
    data = supabase.table("profiles").select("*").order("name").execute().data
    return data or []


def get_profiles_map():
    profiles = get_profiles()
    return {p["slug"]: p for p in profiles}


def get_challenges(category=None):
    query = supabase.table("challenges").select("*").order("sort_order")
    if category:
        query = query.eq("category", category)
    data = query.execute().data
    return data or []


def get_challenges_map():
    result = {}
    for category in CATEGORIES:
        result[category] = get_challenges(category)
    return result


def get_progress_row(profile_slug: str, category: str):
    data = (
        supabase.table("progress")
        .select("*")
        .eq("profile_slug", profile_slug)
        .eq("category", category)
        .order("id")
        .limit(1)
        .execute()
        .data
    )

    if data:
        return data[0]

    row = {
        "profile_slug": profile_slug,
        "category": category,
        "challenge_index": 0,
        "status": "todo",
    }
    supabase.table("progress").insert(row).execute()
    return row


def set_progress(profile_slug: str, category: str, challenge_index: int, status: str):
    existing = (
        supabase.table("progress")
        .select("id")
        .eq("profile_slug", profile_slug)
        .eq("category", category)
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
                "category": category,
                "challenge_index": challenge_index,
                "status": status,
            }
        ).execute()


def update_jokers(profile_slug: str, jokers: int):
    supabase.table("profiles").update({"jokers": jokers}).eq("slug", profile_slug).execute()


def current_challenge(profile_slug: str, category: str):
    progress = get_progress_row(profile_slug, category)
    items = get_challenges(category)
    idx = progress["challenge_index"]

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

    for category in CATEGORIES:
        supabase.table("progress").insert(
            {
                "profile_slug": slug,
                "category": category,
                "challenge_index": 0,
                "status": "todo",
            }
        ).execute()

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


# ---------------------------------------------------
# STYLE
# ---------------------------------------------------
st.markdown(
    """
<style>
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
    padding-top: 1.2rem;
    padding-bottom: 3rem;
}

h1, h2, h3, h4, h5, h6,
p, label, div, span {
    color: #1D1D1D;
    font-family: 'Lato', sans-serif !important;
}

.hero-wrap {
    text-align: center;
    padding: 0.4rem 0 1.35rem 0;
}

.hero-logo-band {
    width: 100%;
    background: linear-gradient(180deg, rgba(255,255,255,0.97), rgba(255,255,255,0.88));
    border: 1px solid rgba(167, 132, 99, 0.10);
    border-radius: 22px;
    padding: 1.15rem 0 0.95rem 0;
    margin: 0 auto 1.1rem auto;
    box-shadow: 0 10px 24px rgba(30, 20, 10, 0.03);
}

.hero-logo-img {
    display: block;
    margin: 0 auto;
    max-width: 132px;
    width: 132px;
    height: auto;
    mix-blend-mode: multiply;
}

.hero-kicker {
    color: #9A6A4B;
    text-transform: uppercase;
    letter-spacing: 0.22em;
    font-size: 0.78rem;
    margin-top: 0.25rem;
    margin-bottom: 0.55rem;
    font-weight: 400;
}

.hero-title {
    font-size: 2.4rem;
    font-weight: 900;
    color: #181818;
    margin-bottom: 0.2rem;
}

.hero-subtitle {
    color: #6B6258;
    font-size: 0.98rem;
    margin-bottom: 0.8rem;
    font-weight: 400;
}

.hero-line {
    width: 170px;
    height: 1px;
    margin: 0 auto;
    background: linear-gradient(90deg, transparent, #B79372, transparent);
}

.panel-box {
    background: rgba(255,255,255,0.78);
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
    margin-bottom: 0.3rem;
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

.challenge-shell {
    background: rgba(255,255,255,0.84);
    border: 1px solid rgba(167, 132, 99, 0.16);
    border-radius: 22px;
    padding: 1rem 1rem 1rem 1rem;
    margin-bottom: 0.55rem;
    box-shadow: 0 12px 28px rgba(30, 20, 10, 0.05);
}

.category-band {
    width: 100%;
    border-radius: 16px;
    padding: 0.95rem 1rem;
    margin: 0 0 1rem 0;
    color: #FFFFFF;
    font-size: 1rem;
    font-weight: 900;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    text-align: center;
    box-shadow: 0 8px 18px rgba(30, 20, 10, 0.08);
}

.meta-line {
    color: #7B6F64;
    font-size: 0.95rem;
    margin-bottom: 0.7rem;
    font-weight: 700;
}

.challenge-text {
    color: #1E1E1E;
    font-size: 1.03rem;
    line-height: 1.72;
    margin: 0.35rem 0 1rem 0;
    white-space: pre-wrap;
}

.status-chip {
    display: inline-block;
    margin-top: 0.05rem;
    margin-bottom: 0.25rem;
    padding: 0.42rem 0.9rem;
    border-radius: 999px;
    background: #F3EEE8;
    border: 1px solid rgba(140, 110, 80, 0.12);
    color: #5A4A3B;
    font-size: 0.84rem;
    font-weight: 700;
}

.state-line {
    color: #5A4A3B;
    font-size: 0.98rem;
    font-weight: 700;
    padding: 0.2rem 0 0.1rem 0;
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
    min-height: 2.2rem;
    font-weight: 700;
    font-size: 0.92rem;
    padding: 0.35rem 0.9rem;
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
    background: rgba(255,255,255,0.9) !important;
    border-radius: 12px !important;
    color: #1D1D1D !important;
    font-family: 'Lato', sans-serif !important;
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
        '<div class="hero-title">DÉFIS</div>'
        '<div class="hero-subtitle">Servir par le jeu</div>'
        '<div class="hero-line"></div>'
        '</div>'
    )

    st.markdown(header_html, unsafe_allow_html=True)


def render_category_card(profile: dict, category: str):
    challenge, progress, items = current_challenge(profile["slug"], category)
    idx = progress["challenge_index"]
    total = len(items)
    status = progress["status"]
    color = COLORS[category]

    safe_category = html_text(category)

    if total == 0:
        body_html = '<div class="state-line">Aucun défi.</div>'
    elif challenge is None:
        body_html = '<div class="state-line">Catégorie terminée.</div>'
    else:
        body_html = (
            f'<div class="meta-line">Défi {idx + 1} sur {total}</div>'
            f'<div class="challenge-text">{html_multiline(challenge["text"])}</div>'
            f'<div class="status-chip">Statut : {html_text(STATUS_LABELS.get(status, "À faire"))}</div>'
        )

    card_html = (
        '<div class="challenge-shell">'
        f'<div class="category-band" style="background:{color};">{safe_category}</div>'
        f'{body_html}'
        '</div>'
    )

    st.markdown(card_html, unsafe_allow_html=True)

    if total > 0 and challenge is not None and status in ["todo", "redo"]:
        c1, c2 = st.columns(2)

        with c1:
            if st.button(
                "✓ Fait",
                key=f"done_{profile['slug']}_{category}",
                use_container_width=True,
            ):
                set_progress(profile["slug"], category, idx, "pending")
                st.rerun()

        with c2:
            disabled = profile["jokers"] <= 0
            if st.button(
                "✦ Joker",
                key=f"joker_{profile['slug']}_{category}",
                use_container_width=True,
                disabled=disabled,
            ):
                update_jokers(profile["slug"], max(0, profile["jokers"] - 1))
                set_progress(profile["slug"], category, idx + 1, "todo")
                st.rerun()

    st.markdown("<div style='height:0.35rem;'></div>", unsafe_allow_html=True)


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

    panel_html = (
        '<div class="panel-box">'
        '<div class="panel-title">Profil</div>'
        f'<div class="panel-value">{html_text(profile["name"])}</div>'
        f'<div class="subtle-text">Jokers restants : {profile["jokers"]}</div>'
        '</div>'
    )

    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown(panel_html, unsafe_allow_html=True)
    with col2:
        st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
        if st.button("Se déconnecter", use_container_width=True):
            st.session_state.logged_profile_slug = None
            st.rerun()

    for category in CATEGORIES:
        render_category_card(profile, category)


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
        profiles_map = get_profiles_map()
        challenges_map = get_challenges_map()

        pending_rows = (
            supabase.table("progress")
            .select("*")
            .eq("status", "pending")
            .order("id")
            .execute()
            .data
        ) or []

        unique_pending = {}
        for row in pending_rows:
            key = (row["profile_slug"], row["category"])
            unique_pending[key] = row

        pending_items = []
        for (_, _), row in unique_pending.items():
            profile = profiles_map.get(row["profile_slug"])
            if not profile:
                continue

            category = row["category"]
            idx = row["challenge_index"]
            items = challenges_map.get(category, [])
            text = items[idx]["text"] if idx < len(items) else "(défi introuvable)"

            pending_items.append(
                {
                    "profile_slug": row["profile_slug"],
                    "profile_name": profile["name"],
                    "category": category,
                    "challenge_index": idx,
                    "text": text,
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
                    f'<div class="compact-main">{html_text(short_text(item["text"], 120))}</div>'
                    '</div>'
                )
                st.markdown(row_html, unsafe_allow_html=True)

                with st.expander("Voir le texte complet"):
                    st.write(item["text"])

                c1, c2 = st.columns(2)
                with c1:
                    if st.button(
                        "Valider",
                        key=f"approve_{item['profile_slug']}_{item['category']}",
                        use_container_width=True,
                    ):
                        set_progress(
                            item["profile_slug"],
                            item["category"],
                            item["challenge_index"] + 1,
                            "todo",
                        )
                        st.rerun()

                with c2:
                    if st.button(
                        "À refaire",
                        key=f"redo_{item['profile_slug']}_{item['category']}",
                        use_container_width=True,
                    ):
                        set_progress(
                            item["profile_slug"],
                            item["category"],
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
