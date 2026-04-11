import base64
import hashlib
import html
import hmac
import mimetypes
import os
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
BASE_DIR = Path(__file__).resolve().parent
ADMIN_PASSWORD = "Boubouboubou122"
PIN_HASH_PREFIX = "pbkdf2_sha256"
PIN_HASH_ITERATIONS = 200_000

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


def get_config_value(name: str, default=None):
    try:
        value = st.secrets[name]
    except Exception:
        value = None

    if isinstance(value, str):
        value = value.strip()

    if value not in (None, ""):
        return value

    env_value = os.getenv(name, "").strip()
    if env_value:
        return env_value

    return default


def require_config_value(name: str) -> str:
    value = get_config_value(name)
    if value:
        return str(value)

    st.error(f"Configuration manquante : {name}. Ajoute-la dans les secrets Streamlit.")
    st.stop()


SUPABASE_URL = require_config_value("SUPABASE_URL")
SUPABASE_KEY = require_config_value("SUPABASE_KEY")

# ---------------------------------------------------
# SUPABASE
# ---------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_supabase_client(url: str, key: str):
    return create_client(url, key)


supabase = get_supabase_client(SUPABASE_URL, SUPABASE_KEY)

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


@st.cache_data(show_spinner=False)
def get_profiles():
    data = supabase.table("profiles").select("*").order("name").execute().data
    return data or []


@st.cache_data(show_spinner=False)
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


def clear_reference_caches():
    get_profiles.clear()
    get_challenges.clear()


def get_global_state_rows():
    data = (
        supabase.table("progress")
        .select("id, profile_slug, challenge_index, status")
        .eq("category", GLOBAL_STATE_KEY)
        .execute()
        .data
    )
    return data or []


def get_global_challenge_index(challenge_id: int):
    for idx, item in enumerate(get_challenges()):
        if item["id"] == challenge_id:
            return idx
    return None


def get_category_insert_index(category: str) -> int:
    items = get_challenges()
    category_rank = CATEGORY_ORDER.get(category, 999)
    last_category_index = None

    for idx, item in enumerate(items):
        item_rank = CATEGORY_ORDER.get(item["category"], 999)

        if item["category"] == category:
            last_category_index = idx
        elif last_category_index is None and item_rank > category_rank:
            return idx

    if last_category_index is not None:
        return last_category_index + 1

    return len(items)


def apply_insertion_progress_policy(insert_index: int, previous_total: int):
    for row in get_global_state_rows():
        current_index = int(row["challenge_index"])
        current_status = row.get("status", "todo")

        if current_index >= previous_total:
            new_index = current_index + 1
            new_status = current_status
        elif current_index >= insert_index:
            new_index = insert_index
            new_status = "todo"
        else:
            continue

        (
            supabase.table("progress")
            .update(
                {
                    "challenge_index": max(0, new_index),
                    "status": new_status,
                }
            )
            .eq("id", row["id"])
            .execute()
        )


def adjust_global_progress_rows_after_deletion(deleted_index: int):
    for row in get_global_state_rows():
        current_index = int(row["challenge_index"])
        current_status = row.get("status", "todo")

        if current_index > deleted_index:
            new_index = current_index - 1
            new_status = current_status
        elif current_index == deleted_index:
            new_index = deleted_index
            new_status = "todo"
        else:
            continue

        (
            supabase.table("progress")
            .update(
                {
                    "challenge_index": max(0, new_index),
                    "status": new_status,
                }
            )
            .eq("id", row["id"])
            .execute()
        )


def count_profiles_on_challenge(challenge_id: int) -> int:
    challenge_index = get_global_challenge_index(challenge_id)
    if challenge_index is None:
        return 0

    return sum(1 for row in get_global_state_rows() if int(row["challenge_index"]) == challenge_index)


def has_active_profiles_on_indices(indices) -> bool:
    tracked_indices = set(indices)
    if not tracked_indices:
        return False

    return any(int(row["challenge_index"]) in tracked_indices for row in get_global_state_rows())


def count_profiles_impacted_by_insert(insert_index: int, previous_total: int) -> int:
    return sum(
        1
        for row in get_global_state_rows()
        if insert_index <= int(row["challenge_index"]) < previous_total
    )


def is_hashed_pin(value: str) -> bool:
    return str(value).startswith(f"{PIN_HASH_PREFIX}$")


def hash_pin(pin: str, salt_hex: str | None = None, iterations: int = PIN_HASH_ITERATIONS) -> str:
    if salt_hex is None:
        salt_hex = os.urandom(16).hex()

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        pin.encode("utf-8"),
        bytes.fromhex(salt_hex),
        int(iterations),
    ).hex()
    return f"{PIN_HASH_PREFIX}${int(iterations)}${salt_hex}${digest}"


def verify_pin(pin: str, stored_pin: str) -> bool:
    stored_pin = str(stored_pin or "")

    if not is_hashed_pin(stored_pin):
        return hmac.compare_digest(pin, stored_pin)

    try:
        _, iterations, salt_hex, expected_digest = stored_pin.split("$", 3)
        computed_digest = hashlib.pbkdf2_hmac(
            "sha256",
            pin.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        ).hex()
    except Exception:
        return False

    return hmac.compare_digest(computed_digest, expected_digest)


def maybe_upgrade_profile_pin(profile_slug: str, raw_pin: str, stored_pin: str):
    if is_hashed_pin(stored_pin):
        return

    supabase.table("profiles").update({"pin": hash_pin(raw_pin)}).eq("slug", profile_slug).execute()
    clear_reference_caches()


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
    clear_reference_caches()


def current_challenge(profile_slug: str):
    progress = get_global_state(profile_slug)
    items = get_challenges()
    idx = int(progress["challenge_index"])

    if idx >= len(items):
        return None, progress, items

    return items[idx], progress, items


def add_profile(name: str, pin: str, jokers: int):
    name = name.strip()
    pin = pin.strip()

    if not name or not pin:
        return False, "Pseudo et PIN obligatoires."

    slug = slugify(name)
    profiles = get_profiles()

    if any(profile["slug"] == slug for profile in profiles):
        return False, "Ce profil existe déjà."

    if any(profile["name"].strip().casefold() == name.casefold() for profile in profiles):
        return False, "Ce pseudo est déjà utilisé."

    supabase.table("profiles").insert(
        {
            "slug": slug,
            "name": name,
            "pin": hash_pin(pin),
            "jokers": int(jokers),
        }
    ).execute()

    set_global_state(slug, 0, "todo")
    set_completed_count(slug, 0)
    clear_reference_caches()

    return True, "Profil créé."


def update_profile(slug: str, name: str, pin: str, jokers: int):
    name = name.strip()
    pin = pin.strip()

    if not name:
        return False, "Pseudo obligatoire."

    current_profile = next((profile for profile in get_profiles() if profile["slug"] == slug), None)
    if current_profile is None:
        return False, "Profil introuvable."

    for profile in get_profiles():
        if profile["slug"] == slug:
            continue
        if profile["name"].strip().casefold() == name.casefold():
            return False, "Ce pseudo est déjà utilisé."

    pin_to_store = current_profile["pin"] if not pin else hash_pin(pin)

    supabase.table("profiles").update(
        {
            "name": name,
            "pin": pin_to_store,
            "jokers": int(jokers),
        }
    ).eq("slug", slug).execute()
    clear_reference_caches()
    return True, "Profil mis à jour."


def delete_profile(slug: str):
    supabase.table("progress").delete().eq("profile_slug", slug).execute()
    supabase.table("profiles").delete().eq("slug", slug).execute()
    clear_reference_caches()

    if st.session_state.logged_profile_slug == slug:
        st.session_state.logged_profile_slug = None


def add_challenge(category: str, text: str):
    text = text.strip()
    if not text:
        return False, "Le texte est vide."

    insert_index = get_category_insert_index(category)
    previous_total = len(get_challenges())
    items = get_challenges(category)
    next_order = len(items) + 1
    supabase.table("challenges").insert(
        {
            "category": category,
            "sort_order": next_order,
            "text": text,
        }
    ).execute()
    apply_insertion_progress_policy(insert_index, previous_total)
    clear_reference_caches()
    return True, "Défi ajouté."


def update_challenge(challenge_id: int, text: str):
    text = text.strip()
    if not text:
        return False, "Le texte est vide."

    supabase.table("challenges").update({"text": text}).eq("id", challenge_id).execute()
    clear_reference_caches()
    return True, "Défi mis à jour."


def delete_challenge(challenge_id: int, category: str):
    global_index = get_global_challenge_index(challenge_id)
    if global_index is None:
        return False, "Défi introuvable."

    supabase.table("challenges").delete().eq("id", challenge_id).execute()
    clear_reference_caches()
    normalize_sort_order(category)
    adjust_global_progress_rows_after_deletion(global_index)
    clear_reference_caches()
    return True, "Défi supprimé."


def normalize_sort_order(category: str):
    clear_reference_caches()
    items = get_challenges(category)
    has_updates = False
    for i, item in enumerate(items, start=1):
        if item["sort_order"] != i:
            supabase.table("challenges").update({"sort_order": i}).eq("id", item["id"]).execute()
            has_updates = True

    if has_updates:
        clear_reference_caches()


def swap_challenge_order(category: str, challenge_id: int, direction: str):
    items = get_challenges(category)
    ids = [item["id"] for item in items]

    if challenge_id not in ids:
        return False, "Défi introuvable."

    idx = ids.index(challenge_id)

    if direction == "up" and idx > 0:
        a = items[idx - 1]
        b = items[idx]
    elif direction == "down" and idx < len(items) - 1:
        a = items[idx]
        b = items[idx + 1]
    else:
        return False, "Déplacement impossible."

    swapped_global_indices = [
        value
        for value in [get_global_challenge_index(a["id"]), get_global_challenge_index(b["id"])]
        if value is not None
    ]

    if has_active_profiles_on_indices(swapped_global_indices):
        return False, "Réorganisation bloquée : un profil est actuellement positionné sur l'un de ces défis."

    supabase.table("challenges").update({"sort_order": b["sort_order"]}).eq("id", a["id"]).execute()
    supabase.table("challenges").update({"sort_order": a["sort_order"]}).eq("id", b["id"]).execute()
    clear_reference_caches()
    return True, "Ordre mis à jour."


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


@st.cache_data(show_spinner=False)
def get_logo_data_uri():
    possible_paths = [BASE_DIR / "logo.jpg", BASE_DIR / "assets" / "logo.jpg"]
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


def get_next_joker_target(completed_count: int) -> int:
    return ((completed_count // 10) + 1) * 10


def get_status_label(status: str, is_completed: bool = False) -> str:
    if is_completed:
        return "Terminé"
    return STATUS_LABELS.get(status, "À faire")


def get_status_message(status: str, is_completed: bool = False) -> str:
    if is_completed:
        return "Parcours visible terminé."
    if status == "pending":
        return "Validation admin en attente."
    if status == "redo":
        return "Défi à refaire."
    return "Défi prêt à être joué."


def build_panel_html(title: str, value: str, subtitle: str = "") -> str:
    subtitle_html = f'<div class="subtle-text">{html_text(subtitle)}</div>' if subtitle else ""
    return (
        '<div class="panel-box">'
        f'<div class="panel-title">{html_text(title)}</div>'
        f'<div class="panel-value">{html_text(value)}</div>'
        f"{subtitle_html}"
        '</div>'
    )


def build_compact_row(title: str, main_text: str, meta_text: str = "") -> str:
    meta_html = f'<div class="compact-meta">{html_text(meta_text)}</div>' if meta_text else ""
    return (
        '<div class="compact-row">'
        f'<div class="compact-top">{html_text(title)}</div>'
        f'<div class="compact-main">{html_text(main_text)}</div>'
        f"{meta_html}"
        '</div>'
    )


def get_profile_snapshot(profile: dict, all_challenges: list) -> dict:
    progress = get_global_state(profile["slug"])
    completed_count = get_completed_count(profile["slug"])
    idx = int(progress["challenge_index"])
    is_completed = idx >= len(all_challenges)
    current_item = None if is_completed else all_challenges[idx]
    current_category = current_item["category"] if current_item else None

    return {
        "profile_slug": profile["slug"],
        "profile_name": profile["name"],
        "jokers": int(profile["jokers"]),
        "completed_count": completed_count,
        "progress_index": idx,
        "progress_status": progress["status"],
        "current_item": current_item,
        "current_category": current_category,
        "current_text": current_item["text"] if current_item else "Parcours terminé",
        "challenge_label": f"{min(idx + 1, len(all_challenges))}/{len(all_challenges)}" if all_challenges else "0/0",
        "is_completed": is_completed,
        "status_label": get_status_label(progress["status"], is_completed=is_completed),
        "status_message": get_status_message(progress["status"], is_completed=is_completed),
    }


def render_user_progress_summary(items, progress, completed_count: int):
    total_challenges = len(items)
    current_index = int(progress["challenge_index"])
    completed_visible = min(current_index, total_challenges)
    remaining_count = max(total_challenges - current_index, 0)
    next_joker_target = get_next_joker_target(completed_count)
    next_joker_gap = max(next_joker_target - completed_count, 0)
    progress_percent = int((completed_visible / total_challenges) * 100) if total_challenges else 0
    summary_html = (
        '<div class="progress-card">'
        '<div class="progress-card-top">'
        '<div class="progress-card-title">Progression</div>'
        f'<div class="progress-card-value">{completed_visible} / {total_challenges} visibles</div>'
        '</div>'
        '<div class="progress-track">'
        f'<div class="progress-fill" style="width:{progress_percent}%;"></div>'
        '</div>'
        '<div class="metric-row">'
        f'<div class="metric-pill"><strong>{completed_count}</strong> validés</div>'
        f'<div class="metric-pill"><strong>{remaining_count}</strong> restants</div>'
        f'<div class="metric-pill">Prochain joker à <strong>{next_joker_target}</strong></div>'
        f'<div class="metric-pill">Encore <strong>{next_joker_gap}</strong> validation(s)</div>'
        '</div>'
        '</div>'
    )
    st.markdown(summary_html, unsafe_allow_html=True)


def render_admin_overview(profiles: list, all_challenges: list):
    snapshots = [get_profile_snapshot(profile, all_challenges) for profile in profiles]
    pending_count = sum(1 for snapshot in snapshots if snapshot["progress_status"] == "pending" and not snapshot["is_completed"])
    redo_count = sum(1 for snapshot in snapshots if snapshot["progress_status"] == "redo" and not snapshot["is_completed"])
    active_count = sum(1 for snapshot in snapshots if not snapshot["is_completed"])
    total_validated = sum(snapshot["completed_count"] for snapshot in snapshots)

    col1, col2, col3, col4, col5, col6 = st.columns(6, gap="small")
    with col1:
        st.markdown(build_panel_html("Profils", str(len(profiles)), "Profils actifs"), unsafe_allow_html=True)
    with col2:
        st.markdown(build_panel_html("En attente", str(pending_count), "Validation admin"), unsafe_allow_html=True)
    with col3:
        st.markdown(build_panel_html("À refaire", str(redo_count), "Blocages en cours"), unsafe_allow_html=True)
    with col4:
        st.markdown(build_panel_html("En parcours", str(active_count), "Hors profils terminés"), unsafe_allow_html=True)
    with col5:
        st.markdown(build_panel_html("Validations", str(total_validated), "Cumul validé"), unsafe_allow_html=True)
    with col6:
        st.markdown(build_panel_html("Défis", str(len(all_challenges)), "Banque totale"), unsafe_allow_html=True)

    st.markdown("### Vue profils")
    filter_col1, filter_col2, filter_col3 = st.columns([1.3, 1.1, 1.6], gap="small")
    with filter_col1:
        status_filter = st.selectbox(
            "Statut",
            ["Tous", "À faire", "En attente de validation", "À refaire", "Terminé"],
            key="overview_status_filter",
        )
    with filter_col2:
        category_filter = st.selectbox("Catégorie", ["Toutes"] + CATEGORIES, key="overview_category_filter")
    with filter_col3:
        profile_filter = st.text_input("Recherche profil", key="overview_profile_filter")

    status_filter_map = {
        "À faire": "todo",
        "En attente de validation": "pending",
        "À refaire": "redo",
    }

    def snapshot_matches(snapshot: dict) -> bool:
        if status_filter == "Terminé" and not snapshot["is_completed"]:
            return False
        if status_filter in status_filter_map and (
            snapshot["is_completed"] or snapshot["progress_status"] != status_filter_map[status_filter]
        ):
            return False
        if status_filter == "Tous":
            pass
        elif status_filter not in status_filter_map and status_filter != "Terminé":
            return False

        if category_filter != "Toutes" and snapshot["current_category"] != category_filter:
            return False

        if profile_filter.strip() and profile_filter.strip().lower() not in snapshot["profile_name"].lower():
            return False

        return True

    snapshots = sorted(
        snapshots,
        key=lambda snapshot: (
            1 if snapshot["is_completed"] else 0,
            {"pending": 0, "redo": 1, "todo": 2}.get(snapshot["progress_status"], 3),
            snapshot["profile_name"].lower(),
        ),
    )

    visible_snapshots = [snapshot for snapshot in snapshots if snapshot_matches(snapshot)]
    if not visible_snapshots:
        st.info("Aucun profil ne correspond aux filtres.")
        return

    for snapshot in visible_snapshots:
        title = f'{snapshot["profile_name"]} • {snapshot["status_label"]}'
        main_text = short_text(snapshot["current_text"], 120)
        meta_bits = [
            f'Position {snapshot["challenge_label"]}',
            f'Validés {snapshot["completed_count"]}',
            f'Jokers {snapshot["jokers"]}',
        ]
        if snapshot["current_category"]:
            meta_bits.insert(1, snapshot["current_category"])

        st.markdown(
            build_compact_row(title, main_text, " • ".join(meta_bits)),
            unsafe_allow_html=True,
        )


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
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(180deg, rgba(255,255,255,0.97), rgba(255,255,255,0.88));
    border: 1px solid rgba(167, 132, 99, 0.10);
    border-radius: 22px;
    padding: 1.15rem 1rem 1rem 1rem;
    min-height: 168px;
    margin: 0 auto 1rem auto;
    box-shadow: 0 10px 24px rgba(30, 20, 10, 0.03);
    overflow: visible;
}

.hero-logo-img {
    display: block;
    margin: 0 auto;
    width: auto;
    max-width: min(100%, 250px);
    max-height: 118px;
    height: auto;
    object-fit: contain;
    object-position: center center;
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

.compact-meta {
    font-size: 0.84rem;
    color: #6F655C;
    line-height: 1.45;
}

.profile-strip {
    background: rgba(255,255,255,0.82);
    border: 1px solid rgba(167, 132, 99, 0.14);
    border-radius: 18px;
    padding: 0.9rem 1rem;
    box-shadow: 0 10px 24px rgba(30, 20, 10, 0.04);
}

.profile-strip-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.8rem;
    margin-bottom: 0.35rem;
}

.profile-strip-name {
    font-size: 1.08rem;
    font-weight: 900;
    color: #181818;
}

.profile-strip-rank {
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: #A06F4A;
    font-weight: 700;
}

.profile-strip-meta {
    color: #655C53;
    font-size: 0.92rem;
    line-height: 1.45;
}

.focus-card {
    background:
        radial-gradient(circle at top right, rgba(139, 30, 63, 0.08), transparent 34%),
        linear-gradient(180deg, rgba(255,255,255,0.98), rgba(252,248,243,0.95));
    border: 1px solid rgba(167, 132, 99, 0.16);
    border-radius: 26px;
    padding: 1.25rem 1.3rem;
    box-shadow: 0 18px 36px rgba(30, 20, 10, 0.06);
}

.focus-card.complete {
    background:
        radial-gradient(circle at top right, rgba(78, 138, 92, 0.10), transparent 36%),
        linear-gradient(180deg, rgba(255,255,255,0.98), rgba(248,252,248,0.96));
}

.focus-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.8rem;
    flex-wrap: wrap;
    margin-bottom: 0.9rem;
}

.focus-title-wrap {
    display: flex;
    align-items: center;
    gap: 0.55rem;
    flex-wrap: wrap;
}

.focus-title {
    font-size: 1.28rem;
    font-weight: 900;
    color: #181818;
}

.focus-position {
    color: #6C625A;
    font-size: 0.92rem;
    font-weight: 700;
}

.focus-text {
    font-size: 1.36rem;
    line-height: 1.52;
    color: #1A1A1A;
    font-weight: 700;
    margin-bottom: 1rem;
}

.focus-footer {
    display: flex;
    align-items: center;
    gap: 0.65rem;
    flex-wrap: wrap;
}

.progress-card {
    background: rgba(255,255,255,0.82);
    border: 1px solid rgba(167, 132, 99, 0.14);
    border-radius: 20px;
    padding: 0.95rem 1rem 1rem 1rem;
    box-shadow: 0 10px 24px rgba(30, 20, 10, 0.04);
}

.progress-card-top {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.8rem;
    margin-bottom: 0.7rem;
}

.progress-card-title {
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.16em;
    color: #A06F4A;
    font-weight: 900;
}

.progress-card-value {
    font-size: 0.96rem;
    font-weight: 800;
    color: #1A1A1A;
}

.progress-track {
    width: 100%;
    height: 10px;
    border-radius: 999px;
    background: #EFE5DA;
    overflow: hidden;
    margin-bottom: 0.85rem;
}

.progress-fill {
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(90deg, #8B1E3F, #B05B75);
}

.metric-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.55rem;
}

.metric-pill {
    background: rgba(255,255,255,0.92);
    border: 1px solid rgba(167, 132, 99, 0.16);
    border-radius: 999px;
    padding: 0.45rem 0.8rem;
    color: #4F453C;
    font-size: 0.86rem;
    font-weight: 700;
}

.metric-pill strong {
    color: #1B1B1B;
    font-weight: 900;
}

.stButton > button {
    width: 100%;
    border-radius: 999px;
    min-height: 2.7rem;
    font-weight: 800;
    font-size: 0.94rem;
    padding: 0.4rem 0.95rem;
    transition: transform 120ms ease, box-shadow 120ms ease, border-color 120ms ease;
}

.stButton > button * {
    fill: currentColor !important;
}

.stButton > button[kind="primary"] {
    border: 1px solid #2E0F13 !important;
    background: #2E0F13 !important;
    color: #FFFFFF !important;
    min-height: 3.35rem;
    font-size: 1.05rem;
    box-shadow: 0 10px 22px rgba(46, 15, 19, 0.22);
}

.stButton > button[kind="secondary"] {
    border: 1px solid rgba(46, 15, 19, 0.18) !important;
    background: rgba(255,255,255,0.92) !important;
    color: #2E0F13 !important;
    box-shadow: 0 6px 14px rgba(30, 20, 10, 0.05);
}

.stButton > button[kind="tertiary"] {
    border: 1px solid transparent !important;
    background: transparent !important;
    color: #6C625A !important;
    min-height: 2.2rem;
    box-shadow: none !important;
}

.stButton > button[kind="primary"] * {
    color: #FFFFFF !important;
    fill: #FFFFFF !important;
}

.stButton > button[kind="secondary"] * {
    color: #2E0F13 !important;
    fill: #2E0F13 !important;
}

.stButton > button[kind="tertiary"] * {
    color: #6C625A !important;
    fill: #6C625A !important;
}

.stButton > button:hover {
    transform: translateY(-1px);
}

.stButton > button[kind="primary"]:hover {
    border-color: #3A1419 !important;
    background: #3A1419 !important;
    color: #FFFFFF !important;
    box-shadow: 0 14px 24px rgba(46, 15, 19, 0.24);
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
        max-width: min(100%, 190px);
        max-height: 96px;
    }

    .hero-title {
        font-size: 1.95rem;
    }

    .hero-subtitle {
        font-size: 0.92rem;
    }

    .current-card,
    .panel-box,
    .challenge-shell,
    .focus-card,
    .progress-card,
    .profile-strip {
        padding: 0.85rem;
    }

    .focus-text {
        font-size: 1.12rem;
    }

    .progress-card-top,
    .focus-top,
    .profile-strip-top {
        flex-direction: column;
        align-items: flex-start;
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
    profile_html = (
        '<div class="profile-strip">'
        '<div class="profile-strip-top">'
        f'<div class="profile-strip-name">{html_text(profile["name"])}</div>'
        f'<div class="profile-strip-rank">{html_text(collar_label)}</div>'
        '</div>'
        f'<div class="profile-strip-meta">Jokers restants : {int(profile["jokers"])} • Défis validés : {completed_count}</div>'
        '</div>'
    )

    meta_col, logout_col = st.columns([6, 1.4], gap="small")
    with meta_col:
        st.markdown(profile_html, unsafe_allow_html=True)
    with logout_col:
        st.markdown("<div style='height:0.55rem;'></div>", unsafe_allow_html=True)
        if st.button("Se déconnecter", use_container_width=True, type="tertiary"):
            st.session_state.logged_profile_slug = None
            st.rerun()

    if current_item is None:
        current_html = (
            '<div class="focus-card complete">'
            '<div class="focus-top">'
            '<div class="focus-title-wrap"><div class="focus-title">Parcours terminé</div></div>'
            '<div class="status-chip">Terminé</div>'
            '</div>'
            '<div class="focus-text">Tous les défis visibles sont franchis.</div>'
            '</div>'
        )
        st.markdown(current_html, unsafe_allow_html=True)
        return

    category = current_item["category"]
    chip_bg = COLORS[category]
    chip_text = CATEGORY_TEXT_COLORS[category]
    status_label = STATUS_LABELS.get(progress["status"], "À faire")

    current_html = (
        '<div class="focus-card">'
        '<div class="focus-top">'
        '<div class="focus-title-wrap">'
        f'<div class="current-category-chip" style="background:{chip_bg}; color:{chip_text};">{html_text(category)}</div>'
        '<div class="focus-title">Défi du moment</div>'
        '</div>'
        f'<div class="focus-position">Défi {int(progress["challenge_index"]) + 1} sur {len(items)}</div>'
        '</div>'
        f'<div class="focus-text">{html_multiline(current_item["text"])}</div>'
        '<div class="focus-footer">'
        f'<div class="status-chip">Statut : {html_text(status_label)}</div>'
        '</div>'
        '</div>'
    )

    st.markdown(current_html, unsafe_allow_html=True)

    if progress["status"] in ["todo", "redo"]:
        c_done, c_joker = st.columns(2, gap="small")
        with c_done:
            if st.button("✓ Fait", key=f"done_{profile['slug']}", use_container_width=True, type="primary"):
                set_global_state(profile["slug"], int(progress["challenge_index"]), "pending")
                st.rerun()
        with c_joker:
            disabled = int(profile["jokers"]) <= 0
            if st.button(
                "✦ Utiliser un joker",
                key=f"joker_{profile['slug']}",
                use_container_width=True,
                disabled=disabled,
                type="secondary",
            ):
                update_jokers(profile["slug"], max(0, int(profile["jokers"]) - 1))
                set_global_state(profile["slug"], int(progress["challenge_index"]) + 1, "todo")
                st.rerun()


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
        with st.form("user_login_form"):
            pseudo = st.text_input("Pseudo")
            pin = st.text_input("Code PIN", type="password")
            submitted = st.form_submit_button("Entrer")

        if submitted:
            profile = find_profile_by_login_input(pseudo, profiles)
            if profile is not None and verify_pin(pin, profile["pin"]):
                maybe_upgrade_profile_pin(profile["slug"], pin, profile["pin"])
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
    render_user_progress_summary(items, progress, completed_count)
    st.markdown("<div style='height:0.45rem;'></div>", unsafe_allow_html=True)
    render_master_list(items, progress)


def render_admin_area():
    st.subheader("Espace admin")

    if not st.session_state.admin_ok:
        with st.form("admin_login_form"):
            password = st.text_input("Mot de passe admin", type="password")
            submitted = st.form_submit_button("Connexion admin")

        if submitted:
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

    profiles = get_profiles()
    all_challenges = get_challenges()

    tab1, tab2, tab3, tab4 = st.tabs(["Vue", "Validations", "Défis", "Profils"])

    with tab1:
        render_admin_overview(profiles, all_challenges)

    with tab2:
        profiles_map = {p["slug"]: p for p in profiles}

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

        st.markdown(
            build_panel_html("En attente", str(len(pending_items)), "Défis à valider"),
            unsafe_allow_html=True,
        )

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

                st.markdown(
                    build_compact_row(
                        f'{item["profile_name"]} • {item["category"]}',
                        short_text(item["text"], 160),
                        f'Défi {item["challenge_index"] + 1}/{len(all_challenges)}',
                    ),
                    unsafe_allow_html=True,
                )

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

    with tab3:
        summary_columns = st.columns(len(CATEGORIES), gap="small")
        for column, summary_category in zip(summary_columns, CATEGORIES):
            challenge_total = len(get_challenges(summary_category))
            with column:
                st.markdown(
                    build_panel_html(summary_category, str(challenge_total), "Défis disponibles"),
                    unsafe_allow_html=True,
                )

        category = st.selectbox("Catégorie", CATEGORIES, key="admin_category")
        items = get_challenges(category)

        st.markdown(
            build_panel_html("Nombre de défis", str(len(items)), "Dans cette catégorie"),
            unsafe_allow_html=True,
        )

        st.markdown("### Ajouter un défi")
        new_challenge = st.text_area("Texte", key=f"new_{category}", height=120)
        impacted_profiles = count_profiles_impacted_by_insert(
            get_category_insert_index(category),
            len(all_challenges),
        )
        if impacted_profiles:
            st.info(
                f"L'ajout dans cette catégorie renverra {impacted_profiles} profil(s) actif(s) vers ce nouveau défi."
            )
        if st.button("Ajouter", key=f"add_{category}", use_container_width=True):
            ok, message = add_challenge(category, new_challenge)
            if ok:
                st.success(message)
                st.rerun()
            else:
                st.error(message)

        st.markdown("### Modifier un défi existant")

        if not items:
            st.info("Aucun défi dans cette catégorie.")
        else:
            search_text = st.text_input("Recherche dans la catégorie", key=f"search_{category}")
            filtered_items = [
                item
                for item in items
                if search_text.strip().lower() in item["text"].lower()
            ]

            if not filtered_items:
                st.info("Aucun défi ne correspond à la recherche.")
            else:
                selected_id = st.selectbox(
                    "Défi",
                    options=[item["id"] for item in filtered_items],
                    format_func=lambda challenge_id: next(
                        f"{i + 1}. {short_text(item['text'], 80)}"
                        for i, item in enumerate(filtered_items)
                        if item["id"] == challenge_id
                    ),
                    key=f"selected_{category}",
                )

                selected_item = next(item for item in items if item["id"] == selected_id)
                assigned_profiles = count_profiles_on_challenge(selected_item["id"])

                if assigned_profiles:
                    st.warning(
                        f"{assigned_profiles} profil(s) sont actuellement positionnés sur ce défi. "
                        "Supprimer reste possible, mais réordonner est bloqué pour éviter un changement silencieux de défi."
                    )

                edited_text = st.text_area(
                    "Texte du défi",
                    value=selected_item["text"],
                    key=f"edit_text_{category}_{selected_id}",
                    height=180,
                )

                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Enregistrer", key=f"save_{category}", use_container_width=True):
                        ok, message = update_challenge(selected_item["id"], edited_text)
                        if ok:
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)
                with c2:
                    if st.button("Supprimer", key=f"delete_{category}", use_container_width=True):
                        ok, message = delete_challenge(selected_item["id"], category)
                        if ok:
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)

                c3, c4 = st.columns(2)
                with c3:
                    if st.button("Monter", key=f"up_{category}", use_container_width=True):
                        ok, message = swap_challenge_order(category, selected_item["id"], "up")
                        if ok:
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)
                with c4:
                    if st.button("Descendre", key=f"down_{category}", use_container_width=True):
                        ok, message = swap_challenge_order(category, selected_item["id"], "down")
                        if ok:
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)

    with tab4:
        st.markdown(
            build_panel_html("Profils", str(len(profiles)), "Gestion des accès et jokers"),
            unsafe_allow_html=True,
        )

        st.markdown("### Ajouter un profil")
        with st.form("new_profile_form"):
            new_name = st.text_input("Pseudo affiché")
            new_pin = st.text_input("PIN", type="password")
            new_jokers = st.number_input("Jokers", min_value=0, max_value=99, value=3, step=1)
            submitted = st.form_submit_button("Créer")

            if submitted:
                ok, message = add_profile(new_name, new_pin, int(new_jokers))
                if ok:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)

        st.markdown("### Modifier un profil")
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
            snapshot = get_profile_snapshot(profile, all_challenges)

            st.markdown(
                build_compact_row(
                    f'{snapshot["profile_name"]} • {snapshot["status_label"]}',
                    short_text(snapshot["current_text"], 140),
                    f'Position {snapshot["challenge_label"]} • Validés {snapshot["completed_count"]} • Jokers {snapshot["jokers"]}',
                ),
                unsafe_allow_html=True,
            )

            updated_name = st.text_input("Pseudo", value=profile["name"], key=f"name_{selected_profile_slug}")
            updated_pin = st.text_input(
                "Nouveau PIN (laisser vide pour garder l'actuel)",
                value="",
                key=f"pin_{selected_profile_slug}",
                type="password",
            )
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
                    ok, message = update_profile(
                        selected_profile_slug,
                        updated_name,
                        updated_pin,
                        int(updated_jokers),
                    )
                    if ok:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)

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
