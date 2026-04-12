import base64
import hashlib
import html
import hmac
import mimetypes
import os
import re
import time
from pathlib import Path

import streamlit as st
from supabase import create_client
try:
    from streamlit_sortables import sort_items
except Exception:
    sort_items = None

st.set_page_config(
    page_title="Prométhée — Défis",
    page_icon="🐺",
    layout="wide",
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
PROFILE_SESSION_PARAM = "ps"
ADMIN_SESSION_PARAM = "as"
AUTH_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30
CHALLENGE_PROOF_BUCKET = "challenge-proofs"
PROOF_MAX_SIZE_BYTES = 5 * 1024 * 1024


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
AUTH_SECRET = str(get_config_value("AUTH_SECRET", SUPABASE_KEY))

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


def challenge_requires_photo(item: dict | None) -> bool:
    return bool((item or {}).get("requires_photo", False))


def html_text(text: str) -> str:
    return html.escape(str(text))


def html_multiline(text: str) -> str:
    return html.escape(str(text)).replace("\n", "<br>")


def get_query_params_dict() -> dict[str, str]:
    try:
        return {str(k): str(v) for k, v in st.query_params.items()}
    except Exception:
        raw_params = st.experimental_get_query_params()
        return {
            str(k): str(v[-1] if isinstance(v, list) else v)
            for k, v in raw_params.items()
        }


def set_query_params_dict(params: dict[str, str]):
    cleaned = {str(k): str(v) for k, v in params.items() if v not in (None, "")}

    try:
        st.query_params.clear()
        for key, value in cleaned.items():
            st.query_params[key] = value
    except Exception:
        st.experimental_set_query_params(**cleaned)


def set_query_param_value(name: str, value: str | None):
    params = get_query_params_dict()
    if value in (None, ""):
        params.pop(name, None)
    else:
        params[name] = value
    set_query_params_dict(params)


def encode_auth_token(kind: str, subject: str, ttl_seconds: int = AUTH_TOKEN_TTL_SECONDS) -> str:
    expires_at = int(time.time()) + int(ttl_seconds)
    payload = f"{kind}|{subject}|{expires_at}"
    signature = hmac.new(
        AUTH_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    token_bytes = f"{payload}|{signature}".encode("utf-8")
    return base64.urlsafe_b64encode(token_bytes).decode("utf-8").rstrip("=")


def decode_auth_token(token: str | None):
    if not token:
        return None

    try:
        padded = str(token) + "=" * (-len(str(token)) % 4)
        raw_value = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
        kind, subject, expires_at_str, signature = raw_value.split("|", 3)
        payload = f"{kind}|{subject}|{expires_at_str}"
        expected_signature = hmac.new(
            AUTH_SECRET.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            return None
        if int(expires_at_str) < int(time.time()):
            return None
        return {
            "kind": kind,
            "subject": subject,
            "expires_at": int(expires_at_str),
        }
    except Exception:
        return None


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


def persist_profile_session(profile_slug: str):
    set_query_param_value(PROFILE_SESSION_PARAM, encode_auth_token("profile", profile_slug))


def clear_profile_session():
    set_query_param_value(PROFILE_SESSION_PARAM, None)


def persist_admin_session():
    set_query_param_value(ADMIN_SESSION_PARAM, encode_auth_token("admin", "admin"))


def clear_admin_session():
    set_query_param_value(ADMIN_SESSION_PARAM, None)


def restore_persistent_sessions():
    profile_token = decode_auth_token(get_query_params_dict().get(PROFILE_SESSION_PARAM))
    if profile_token and profile_token["kind"] == "profile":
        valid_slugs = {profile["slug"] for profile in get_profiles()}
        if profile_token["subject"] in valid_slugs:
            st.session_state.logged_profile_slug = profile_token["subject"]
        else:
            clear_profile_session()
    elif get_query_params_dict().get(PROFILE_SESSION_PARAM):
        clear_profile_session()

    admin_token = decode_auth_token(get_query_params_dict().get(ADMIN_SESSION_PARAM))
    if admin_token and admin_token["kind"] == "admin" and admin_token["subject"] == "admin":
        st.session_state.admin_ok = True
    elif get_query_params_dict().get(ADMIN_SESSION_PARAM):
        clear_admin_session()


restore_persistent_sessions()


def get_challenge_feature_status() -> dict[str, bool]:
    status = {
        "requires_photo_column": False,
        "submissions_table": False,
    }

    try:
        supabase.table("challenges").select("id, requires_photo").limit(1).execute()
        status["requires_photo_column"] = True
    except Exception:
        pass

    try:
        supabase.table("challenge_submissions").select("id").limit(1).execute()
        status["submissions_table"] = True
    except Exception:
        pass

    return status


def is_photo_feature_ready() -> bool:
    status = get_challenge_feature_status()
    return status["requires_photo_column"] and status["submissions_table"]


def get_photo_feature_setup_message() -> str:
    return (
        "La preuve photo demande le script SQL `SUPABASE_SETUP_PHOTO_PROOFS.sql` dans le repo "
        "avant de pouvoir être utilisée."
    )


def ensure_proof_bucket():
    try:
        supabase.storage.get_bucket(CHALLENGE_PROOF_BUCKET)
        return True, None
    except Exception:
        pass

    try:
        supabase.storage.create_bucket(
            CHALLENGE_PROOF_BUCKET,
            options={
                "public": False,
                "allowed_mime_types": ["image/jpeg", "image/png", "image/webp"],
                "file_size_limit": PROOF_MAX_SIZE_BYTES,
            },
        )
        return True, None
    except Exception as exc:
        return False, (
            "Bucket de preuves photo introuvable et création automatique impossible. "
            f"Crée le bucket privé `{CHALLENGE_PROOF_BUCKET}` dans Supabase Storage. "
            f"Détail: {exc}"
        )


def get_submission(profile_slug: str, challenge_id: int):
    try:
        data = (
            supabase.table("challenge_submissions")
            .select("*")
            .eq("profile_slug", profile_slug)
            .eq("challenge_id", challenge_id)
            .limit(1)
            .execute()
            .data
        )
    except Exception:
        return None

    return data[0] if data else None


def get_submissions_for_challenge(challenge_id: int):
    try:
        data = (
            supabase.table("challenge_submissions")
            .select("*")
            .eq("challenge_id", challenge_id)
            .execute()
            .data
        )
        return data or []
    except Exception:
        return []


def sanitize_file_extension(filename: str, mime_type: str | None = None) -> str:
    ext = Path(str(filename or "")).suffix.lower().strip(".")
    if ext in {"jpg", "jpeg", "png", "webp"}:
        return "jpg" if ext == "jpeg" else ext

    guessed = mimetypes.guess_extension(mime_type or "") or ""
    guessed = guessed.lower().strip(".")
    if guessed in {"jpg", "jpeg", "png", "webp"}:
        return "jpg" if guessed == "jpeg" else guessed

    return "jpg"


def delete_proof_file(photo_path: str | None):
    if not photo_path:
        return

    try:
        supabase.storage.from_(CHALLENGE_PROOF_BUCKET).remove([photo_path])
    except Exception:
        pass


def delete_submission(profile_slug: str, challenge_id: int):
    submission = get_submission(profile_slug, challenge_id)
    if submission:
        delete_proof_file(submission.get("photo_path"))

    try:
        (
            supabase.table("challenge_submissions")
            .delete()
            .eq("profile_slug", profile_slug)
            .eq("challenge_id", challenge_id)
            .execute()
        )
    except Exception:
        pass


def save_photo_submission(profile_slug: str, challenge_id: int, uploaded_file):
    if not is_photo_feature_ready():
        return False, get_photo_feature_setup_message()

    ok, bucket_message = ensure_proof_bucket()
    if not ok:
        return False, bucket_message

    if uploaded_file is None:
        return False, "Choisis une photo avant d'envoyer la validation."

    file_bytes = uploaded_file.getvalue()
    if not file_bytes:
        return False, "Le fichier est vide."

    if len(file_bytes) > PROOF_MAX_SIZE_BYTES:
        return False, "La photo dépasse la limite de 5 Mo."

    extension = sanitize_file_extension(uploaded_file.name, getattr(uploaded_file, "type", None))
    photo_path = f"{profile_slug}/challenge-{challenge_id}-{int(time.time() * 1000)}.{extension}"
    existing_submission = get_submission(profile_slug, challenge_id)

    if existing_submission:
        delete_proof_file(existing_submission.get("photo_path"))

    try:
        supabase.storage.from_(CHALLENGE_PROOF_BUCKET).upload(photo_path, file_bytes)
    except Exception as exc:
        return False, f"Impossible d'envoyer la photo dans Storage : {exc}"

    payload = {
        "profile_slug": profile_slug,
        "challenge_id": challenge_id,
        "photo_path": photo_path,
        "photo_filename": uploaded_file.name or Path(photo_path).name,
        "photo_mime_type": getattr(uploaded_file, "type", None) or mimetypes.guess_type(photo_path)[0],
    }

    try:
        if existing_submission:
            (
                supabase.table("challenge_submissions")
                .update(payload)
                .eq("id", existing_submission["id"])
                .execute()
            )
        else:
            supabase.table("challenge_submissions").insert(payload).execute()
    except Exception as exc:
        delete_proof_file(photo_path)
        return False, f"Impossible d'enregistrer la preuve photo : {exc}"

    return True, "Preuve photo enregistrée."


def download_submission_photo(submission: dict):
    photo_path = submission.get("photo_path")
    if not photo_path:
        return None, "Chemin de photo introuvable."

    try:
        file_bytes = supabase.storage.from_(CHALLENGE_PROOF_BUCKET).download(photo_path)
        return file_bytes, None
    except Exception as exc:
        return None, f"Impossible de récupérer la photo : {exc}"


def preserve_progress_after_reorder(old_items: list[dict], new_items: list[dict]):
    old_ids_by_index = [item["id"] for item in old_items]
    new_index_by_id = {item["id"]: idx for idx, item in enumerate(new_items)}

    for row in get_global_state_rows():
        current_index = int(row["challenge_index"])
        if current_index >= len(old_ids_by_index):
            continue

        current_challenge_id = old_ids_by_index[current_index]
        new_index = new_index_by_id.get(current_challenge_id)
        if new_index is None or new_index == current_index:
            continue

        (
            supabase.table("progress")
            .update({"challenge_index": new_index})
            .eq("id", row["id"])
            .execute()
        )


def save_challenge_order(category: str, ordered_ids: list[int]):
    items = get_challenges(category)
    current_ids = [item["id"] for item in items]
    if sorted(current_ids) != sorted(ordered_ids):
        return False, "La nouvelle liste ne correspond pas aux défis de cette catégorie."

    old_items = get_challenges()
    id_to_item = {item["id"]: item for item in items}

    for index, challenge_id in enumerate(ordered_ids, start=1):
        if id_to_item[challenge_id]["sort_order"] != index:
            (
                supabase.table("challenges")
                .update({"sort_order": index})
                .eq("id", challenge_id)
                .execute()
            )

    clear_reference_caches()
    new_items = get_challenges()
    preserve_progress_after_reorder(old_items, new_items)
    clear_reference_caches()
    return True, "Ordre mis à jour."


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
    if get_challenge_feature_status()["submissions_table"]:
        try:
            submissions = (
                supabase.table("challenge_submissions")
                .select("challenge_id")
                .eq("profile_slug", slug)
                .execute()
                .data
            ) or []
            for submission in submissions:
                delete_submission(slug, int(submission["challenge_id"]))
        except Exception:
            pass

    supabase.table("progress").delete().eq("profile_slug", slug).execute()
    supabase.table("profiles").delete().eq("slug", slug).execute()
    clear_reference_caches()

    if st.session_state.logged_profile_slug == slug:
        st.session_state.logged_profile_slug = None
        clear_profile_session()


def add_challenge(category: str, text: str, requires_photo: bool = False):
    text = text.strip()
    if not text:
        return False, "Le texte est vide."

    insert_index = get_category_insert_index(category)
    previous_total = len(get_challenges())
    items = get_challenges(category)
    next_order = len(items) + 1
    payload = {
        "category": category,
        "sort_order": next_order,
        "text": text,
    }
    feature_status = get_challenge_feature_status()
    if requires_photo:
        if not feature_status["requires_photo_column"]:
            return False, get_photo_feature_setup_message()
        payload["requires_photo"] = True
    elif feature_status["requires_photo_column"]:
        payload["requires_photo"] = False

    supabase.table("challenges").insert(payload).execute()
    apply_insertion_progress_policy(insert_index, previous_total)
    clear_reference_caches()
    return True, "Défi ajouté."


def update_challenge(challenge_id: int, text: str, requires_photo: bool = False):
    text = text.strip()
    if not text:
        return False, "Le texte est vide."

    payload = {"text": text}
    feature_status = get_challenge_feature_status()
    if feature_status["requires_photo_column"]:
        payload["requires_photo"] = bool(requires_photo)
    elif requires_photo:
        return False, get_photo_feature_setup_message()

    supabase.table("challenges").update(payload).eq("id", challenge_id).execute()
    clear_reference_caches()
    return True, "Défi mis à jour."


def delete_challenge(challenge_id: int, category: str):
    global_index = get_global_challenge_index(challenge_id)
    if global_index is None:
        return False, "Défi introuvable."

    if get_challenge_feature_status()["submissions_table"]:
        for submission in get_submissions_for_challenge(challenge_id):
            delete_submission(submission["profile_slug"], challenge_id)

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
    possible_paths = [
        BASE_DIR / "logo.png",
        BASE_DIR / "logo.jpg",
        BASE_DIR / "assets" / "logo.png",
        BASE_DIR / "assets" / "logo.jpg",
    ]
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
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800;900&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

:root {
    --bg: #FBF7F3;
    --surface: rgba(255, 253, 252, 0.94);
    --surface-strong: rgba(255, 255, 255, 0.98);
    --ink: #2A1318;
    --ink-soft: #65545A;
    --accent: #4A1822;
    --accent-soft: #A25567;
    --line: #E7D9D0;
    --line-strong: #D9C4BA;
    --success: #335645;
    --warning: #A06F4A;
}

html, body, [class*="css"], [data-testid="stAppViewContainer"], [data-testid="stMarkdownContainer"] {
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    -webkit-text-size-adjust: 100%;
}

.stApp {
    background:
        radial-gradient(circle at top, rgba(162, 85, 103, 0.08), transparent 30%),
        linear-gradient(180deg, var(--bg) 0%, #F8F1EC 100%);
    overflow-x: hidden;
}

[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
#MainMenu,
footer {
    display: none !important;
}

.block-container {
    max-width: 1140px;
    margin: 0 auto;
    padding-top: 0.45rem;
    padding-bottom: 2.2rem;
}

h1, h2, h3, h4, h5, h6,
p, label, div, span {
    color: var(--ink);
    font-family: 'Plus Jakarta Sans', sans-serif !important;
}

h1, h2, h3, .hero-title, .focus-title, .profile-strip-name {
    font-family: 'Outfit', sans-serif !important;
}

.hero-wrap {
    text-align: center;
    padding: 0.1rem 0 1.15rem 0;
}

.hero-logo-band {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0.35rem 1rem 0.3rem 1rem;
    min-height: 98px;
    margin: 0 auto 0.8rem auto;
    box-shadow: none;
    overflow: visible;
}

.hero-logo-img {
    display: block;
    margin: 0 auto;
    width: auto;
    max-width: min(100%, 214px);
    max-height: 94px;
    height: auto;
    object-fit: contain;
    object-position: center center;
    mix-blend-mode: normal;
}

.hero-kicker {
    color: var(--accent-soft);
    text-transform: uppercase;
    letter-spacing: 0.34em;
    font-size: 0.74rem;
    margin-top: 0.15rem;
    margin-bottom: 0.3rem;
    font-weight: 800;
}

.hero-title {
    font-size: 2.82rem;
    font-weight: 900;
    color: var(--ink);
    letter-spacing: -0.05em;
    line-height: 0.96;
    margin-bottom: 0.15rem;
}

.hero-subtitle {
    color: var(--ink-soft);
    font-size: 0.98rem;
    margin-bottom: 0.75rem;
    font-weight: 500;
}

.hero-line {
    width: 224px;
    height: 1px;
    margin: 0 auto;
    background: linear-gradient(90deg, transparent, rgba(74, 24, 34, 0.68), transparent);
}

.panel-box {
    background: var(--surface-strong);
    border: 1px solid var(--line);
    border-top: 3px solid rgba(74, 24, 34, 0.2);
    border-radius: 18px;
    padding: 1rem 1rem 1.02rem 1rem;
    margin-bottom: 1rem;
    box-shadow: 0 18px 36px rgba(54, 25, 31, 0.03);
}

.panel-title {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.24em;
    color: var(--accent-soft);
    margin-bottom: 0.38rem;
    font-weight: 800;
}

.panel-value {
    color: var(--ink);
    font-size: 1.06rem;
    font-weight: 800;
}

.subtle-text {
    color: var(--ink-soft);
    font-size: 0.92rem;
}

.collar-chip {
    display: inline-block;
    margin-top: 0.55rem;
    padding: 0.4rem 0.82rem;
    border-radius: 12px;
    font-size: 0.78rem;
    font-weight: 800;
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
    padding: 0.36rem 0.7rem;
    border-radius: 11px;
    font-size: 0.68rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.16em;
    border: 1px solid rgba(0, 0, 0, 0.05);
}

.current-card-text {
    font-size: 1.04rem;
    line-height: 1.68;
    color: #1E1E1E;
}

.status-chip {
    display: inline-block;
    margin-top: 0.25rem;
    padding: 0.45rem 0.85rem;
    border-radius: 12px;
    background: rgba(74, 24, 34, 0.04);
    border: 1px solid rgba(217, 196, 186, 0.88);
    color: var(--ink-soft);
    font-size: 0.8rem;
    font-weight: 700;
}

.challenge-shell {
    background: var(--surface-strong);
    border: 1px solid var(--line);
    border-radius: 20px;
    padding: 1.05rem 1.05rem 0.95rem 1.05rem;
    margin-bottom: 0.55rem;
    box-shadow: 0 18px 36px rgba(54, 25, 31, 0.03);
}

.list-title {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.26em;
    color: var(--accent);
    margin-bottom: 0.92rem;
    font-weight: 800;
    font-family: 'Outfit', sans-serif !important;
}

.challenge-progress-list {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.48rem;
}

.challenge-progress-row {
    border-radius: 12px;
    padding: 0.8rem 0.92rem;
    border: 1px solid rgba(217, 196, 186, 0.84);
    background: rgba(255, 255, 255, 0.78);
    display: flex;
    align-items: flex-start;
    gap: 0.72rem;
    transition: border-color 120ms ease, box-shadow 120ms ease, background 120ms ease;
}

.challenge-progress-index {
    min-width: 34px;
    width: 34px;
    height: 34px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.82rem;
    font-weight: 900;
    background: rgba(74, 24, 34, 0.06);
    color: var(--accent);
    border: 1px solid rgba(217, 196, 186, 0.96);
    flex-shrink: 0;
}

.challenge-progress-category {
    min-width: 82px;
    padding: 0.36rem 0.58rem;
    border-radius: 10px;
    font-size: 0.68rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    text-align: center;
    flex-shrink: 0;
    margin-top: 1px;
    border: 1px solid rgba(0, 0, 0, 0.04);
}

.challenge-progress-text {
    flex: 1;
    font-size: 0.97rem;
    line-height: 1.6;
    color: var(--ink);
    word-break: break-word;
}

.challenge-progress-row.done {
    background: rgba(51, 86, 69, 0.05);
    border-color: rgba(51, 86, 69, 0.18);
}

.challenge-progress-row.done .challenge-progress-index {
    background: var(--success);
    color: #FFFFFF;
    border-color: var(--success);
}

.challenge-progress-row.current {
    background: var(--surface-strong);
    border-color: rgba(74, 24, 34, 0.28);
    box-shadow: 0 14px 28px rgba(74, 24, 34, 0.06);
}

.challenge-progress-row.current .challenge-progress-index {
    background: var(--accent);
    color: #FFFFFF;
    border-color: var(--accent);
}

.challenge-progress-row.pending {
    background: rgba(160, 111, 74, 0.06);
    border-color: rgba(160, 111, 74, 0.18);
}

.challenge-progress-row.pending .challenge-progress-index {
    background: var(--warning);
    color: #FFFFFF;
    border-color: var(--warning);
}

.challenge-progress-row.locked {
    background: rgba(255, 253, 252, 0.55);
    border-color: rgba(217, 196, 186, 0.55);
    border-style: dashed;
}

.challenge-progress-row.locked .challenge-progress-text {
    filter: blur(3px);
    opacity: 0.68;
    user-select: none;
    pointer-events: none;
}

.challenge-progress-row.locked .challenge-progress-index {
    background: rgba(233, 226, 217, 0.9);
    color: #8B7E71;
}

.challenge-progress-row.redo {
    background: rgba(162, 85, 103, 0.05);
    border-color: rgba(162, 85, 103, 0.2);
}

.challenge-progress-row.redo .challenge-progress-index {
    background: var(--accent-soft);
    color: #FFFFFF;
    border-color: var(--accent-soft);
}

.compact-row {
    background: var(--surface-strong);
    border: 1px solid var(--line);
    border-left: 3px solid rgba(74, 24, 34, 0.16);
    border-radius: 16px;
    padding: 0.85rem 0.95rem 0.72rem 0.95rem;
    margin-bottom: 0.65rem;
    box-shadow: 0 14px 24px rgba(54, 25, 31, 0.025);
}

.compact-top {
    font-size: 0.72rem;
    color: var(--accent-soft);
    margin-bottom: 0.34rem;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    font-weight: 800;
}

.compact-main {
    font-size: 0.98rem;
    font-weight: 700;
    color: var(--ink);
    margin-bottom: 0.45rem;
    line-height: 1.52;
}

.compact-meta {
    font-size: 0.84rem;
    color: var(--ink-soft);
    line-height: 1.5;
}

.profile-strip {
    background: var(--surface-strong);
    border: 1px solid var(--line);
    border-radius: 20px;
    padding: 0.88rem 1.02rem;
    box-shadow: 0 14px 26px rgba(54, 25, 31, 0.025);
}

.profile-strip-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.8rem;
    margin-bottom: 0.25rem;
}

.profile-strip-name {
    font-size: 1.16rem;
    font-weight: 900;
    color: var(--ink);
}

.profile-strip-rank {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.22em;
    color: var(--accent-soft);
    font-weight: 800;
}

.profile-strip-meta {
    color: var(--ink-soft);
    font-size: 0.9rem;
    line-height: 1.5;
}

.focus-card {
    background: var(--surface-strong);
    border: 1px solid var(--line-strong);
    border-top: 2px solid rgba(74, 24, 34, 0.48);
    border-radius: 24px;
    padding: 1.22rem 1.38rem 1.18rem 1.38rem;
    box-shadow: 0 20px 38px rgba(54, 25, 31, 0.045);
}

.focus-card.complete {
    border-top-color: var(--success);
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
    gap: 0.7rem;
    flex-wrap: wrap;
}

.focus-title {
    font-size: 1.06rem;
    font-weight: 800;
    color: var(--ink);
    letter-spacing: -0.02em;
}

.focus-position {
    color: var(--accent-soft);
    font-size: 0.76rem;
    font-weight: 800;
    letter-spacing: 0.16em;
    text-transform: uppercase;
}

.focus-text {
    font-family: 'Outfit', sans-serif !important;
    font-size: 1.58rem;
    line-height: 1.22;
    color: var(--ink);
    font-weight: 800;
    letter-spacing: -0.03em;
    margin-bottom: 1rem;
    max-width: 36ch;
}

.focus-footer {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    flex-wrap: wrap;
}

.progress-card {
    background: var(--surface-strong);
    border: 1px solid var(--line);
    border-radius: 20px;
    padding: 1rem 1.05rem 1.05rem 1.05rem;
    box-shadow: 0 18px 32px rgba(54, 25, 31, 0.03);
}

.progress-card-top {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.8rem;
    margin-bottom: 0.7rem;
}

.progress-card-title {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.24em;
    color: var(--accent-soft);
    font-weight: 800;
}

.progress-card-value {
    font-size: 0.98rem;
    font-weight: 800;
    color: var(--accent);
}

.progress-track {
    width: 100%;
    height: 8px;
    border-radius: 999px;
    background: rgba(74, 24, 34, 0.08);
    overflow: hidden;
    margin-bottom: 0.92rem;
}

.progress-fill {
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(90deg, var(--accent), var(--accent-soft));
}

.metric-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.55rem;
}

.metric-pill {
    background: rgba(255, 255, 255, 0.84);
    border: 1px solid rgba(217, 196, 186, 0.9);
    border-radius: 12px;
    padding: 0.52rem 0.78rem;
    color: var(--ink-soft);
    font-size: 0.84rem;
    font-weight: 700;
}

.metric-pill strong {
    color: var(--ink);
    font-weight: 900;
}

.stButton > button {
    width: 100%;
    border-radius: 16px;
    min-height: 2.95rem;
    font-weight: 800;
    font-size: 0.94rem;
    padding: 0.45rem 0.95rem;
    transition: transform 120ms ease, box-shadow 120ms ease, border-color 120ms ease, background 120ms ease;
}

.stButton > button * {
    fill: currentColor !important;
}

.stButton > button[kind="primary"] {
    border: 1px solid var(--accent) !important;
    background: var(--accent) !important;
    color: #FFFFFF !important;
    min-height: 3.18rem;
    font-size: 1.02rem;
    box-shadow: 0 14px 24px rgba(46, 15, 19, 0.18);
}

.stButton > button[kind="secondary"] {
    border: 1px solid rgba(74, 24, 34, 0.16) !important;
    background: rgba(255,253,252,0.34) !important;
    color: var(--accent) !important;
    box-shadow: none !important;
}

.stButton > button[kind="tertiary"] {
    border: 1px solid transparent !important;
    background: transparent !important;
    color: var(--ink-soft) !important;
    min-height: 1.8rem;
    width: auto !important;
    margin-left: auto;
    padding-left: 0 !important;
    padding-right: 0 !important;
    box-shadow: none !important;
    border-radius: 0 !important;
    font-size: 0.9rem;
    font-weight: 700;
}

.stButton > button[kind="primary"] * {
    color: #FFFFFF !important;
    fill: #FFFFFF !important;
}

.stButton > button[kind="secondary"] * {
    color: var(--accent) !important;
    fill: var(--accent) !important;
}

.stButton > button[kind="tertiary"] * {
    color: var(--ink-soft) !important;
    fill: var(--ink-soft) !important;
}

.stButton > button:hover {
    transform: translateY(-1px);
}

.stButton > button[kind="primary"]:hover {
    border-color: #341116 !important;
    background: #341116 !important;
    color: #FFFFFF !important;
    box-shadow: 0 18px 28px rgba(46, 15, 19, 0.2);
}

.stButton > button[kind="secondary"]:hover {
    border-color: rgba(74, 24, 34, 0.28) !important;
    background: rgba(255,255,255,0.72) !important;
}

.stButton > button[kind="tertiary"]:hover {
    transform: none;
    color: var(--accent) !important;
}

.stTextInput > div > div > input,
.stTextArea textarea,
.stSelectbox div[data-baseweb="select"] > div,
.stNumberInput input {
    background: rgba(255,255,255,0.98) !important;
    border-radius: 14px !important;
    color: var(--ink) !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    border: 1px solid rgba(217, 196, 186, 0.96) !important;
    box-shadow: none !important;
}

.stSelectbox div[data-baseweb="select"] span,
.stSelectbox div[data-baseweb="select"] div {
    color: #1D1D1D !important;
}

div[data-baseweb="popover"] {
    background: #FFFFFF !important;
    border-radius: 14px !important;
    border: 1px solid var(--line) !important;
    box-shadow: 0 18px 32px rgba(54, 25, 31, 0.08) !important;
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
    background: #F7F1EC !important;
    color: #1D1D1D !important;
}

div[data-baseweb="popover"] [role="option"][aria-selected="true"] {
    background: rgba(74, 24, 34, 0.07) !important;
    color: #1D1D1D !important;
}

div[data-baseweb="popover"] [role="option"][aria-selected="true"] * {
    color: #1D1D1D !important;
}

.stTabs [data-baseweb="tab"] {
    color: var(--ink-soft);
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-weight: 700;
}

.stTabs [aria-selected="true"] {
    color: var(--accent) !important;
}

.stRadio div[role="radiogroup"] {
    gap: 0.85rem;
    flex-wrap: wrap;
}

.stRadio label {
    color: var(--ink) !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important;
}

.stRadio > label {
    font-size: 0.92rem !important;
    font-weight: 600 !important;
    color: var(--ink-soft) !important;
    margin-bottom: 0.3rem !important;
}

div[data-testid="stRadio"] {
    max-width: 360px;
    margin-left: auto;
    margin-right: auto;
    margin-bottom: 1rem;
}

div[data-testid="stRadio"] label[data-baseweb="radio"] {
    background: rgba(255, 255, 255, 0.55);
    border: 1px solid rgba(217, 196, 186, 0.72);
    border-radius: 999px;
    padding: 0.46rem 0.9rem 0.46rem 0.72rem;
}

div[data-testid="stRadio"] label[data-baseweb="radio"] > div {
    gap: 0.38rem;
}

div[data-testid="stRadio"] label[data-baseweb="radio"] p,
div[data-testid="stRadio"] label[data-baseweb="radio"] span {
    white-space: nowrap !important;
    word-break: keep-all !important;
    overflow-wrap: normal !important;
}

div[data-testid="stForm"] {
    background: var(--surface-strong);
    border: 1px solid var(--line);
    border-top: 2px solid rgba(74, 24, 34, 0.22);
    border-radius: 20px;
    max-width: 620px;
    margin-left: auto;
    margin-right: auto;
    padding: 1.15rem 1.15rem 0.45rem 1.15rem;
    box-shadow: 0 20px 36px rgba(54, 25, 31, 0.035);
}

.auth-title {
    font-family: 'Outfit', sans-serif !important;
    font-size: 1.08rem;
    font-weight: 800;
    color: var(--ink);
    max-width: 620px;
    margin: 0 auto 0.8rem auto;
}

div[data-testid="stFormSubmitButton"] > button,
.stForm [data-testid="stFormSubmitButton"] > button {
    width: 100% !important;
    border: 1px solid var(--accent) !important;
    background: var(--accent) !important;
    color: #FFFFFF !important;
    border-radius: 14px !important;
    min-height: 3.1rem !important;
    font-weight: 800 !important;
    font-size: 1rem !important;
    box-shadow: 0 14px 24px rgba(46, 15, 19, 0.18) !important;
}

div[data-testid="stFormSubmitButton"] > button *,
.stForm [data-testid="stFormSubmitButton"] > button * {
    color: #FFFFFF !important;
    fill: #FFFFFF !important;
}

div[data-testid="stFormSubmitButton"] > button:hover,
.stForm [data-testid="stFormSubmitButton"] > button:hover {
    border-color: #341116 !important;
    background: #341116 !important;
    box-shadow: 0 18px 28px rgba(46, 15, 19, 0.2) !important;
}

.stTextInput > label,
.stTextArea > label,
.stNumberInput > label,
.stSelectbox > label {
    font-size: 0.86rem !important;
    font-weight: 700 !important;
    color: var(--ink) !important;
}

.stTextInput > div > div > input,
.stNumberInput input {
    min-height: 3rem !important;
}

.stTextInput > div > div > input:focus,
.stTextArea textarea:focus,
.stNumberInput input:focus {
    border-color: rgba(74, 24, 34, 0.34) !important;
    box-shadow: 0 0 0 1px rgba(74, 24, 34, 0.14) !important;
}

@media (max-width: 768px) {
    .block-container {
        padding-top: 0.45rem;
        padding-bottom: 1.25rem;
        padding-left: 0.72rem;
        padding-right: 0.72rem;
    }

    .hero-wrap {
        padding: 0.05rem 0 0.85rem 0;
    }

    div[data-testid="stHorizontalBlock"] {
        flex-direction: column;
        gap: 0.62rem;
    }

    div[data-testid="column"] {
        width: 100% !important;
        flex: 1 1 100% !important;
        min-width: 0 !important;
    }

    .stRadio div[role="radiogroup"] {
        flex-direction: row;
        align-items: stretch;
        justify-content: center;
        gap: 0.45rem;
        width: 100%;
    }

    div[data-baseweb="tab-list"] {
        flex-wrap: wrap;
        gap: 0.35rem;
        overflow-x: visible;
    }

    div[data-testid="stRadio"] label[data-baseweb="radio"] {
        flex: 0 0 auto;
        justify-content: center;
        text-align: center;
        padding: 0.42rem 0.7rem;
        min-width: fit-content;
        font-size: 0.94rem;
    }

    .hero-logo-img {
        max-width: min(100%, 148px);
        max-height: 68px;
    }

    .hero-title {
        font-size: 1.86rem;
    }

    .hero-subtitle {
        font-size: 0.86rem;
    }

    .hero-kicker {
        font-size: 0.66rem;
        letter-spacing: 0.28em;
    }

    .hero-line {
        width: 154px;
    }

    .hero-logo-band {
        min-height: 62px;
        padding: 0.05rem 0.8rem 0.02rem 0.8rem;
    }

    .current-card,
    .panel-box,
    .challenge-shell,
    .focus-card,
    .progress-card,
    .profile-strip {
        padding: 0.8rem;
        border-radius: 16px;
    }

    .panel-box {
        padding: 0.8rem 0.82rem 0.85rem 0.82rem;
    }

    .profile-strip {
        padding: 0.78rem 0.84rem;
    }

    .focus-text {
        font-size: 1.08rem;
        line-height: 1.28;
        max-width: none;
    }

    .focus-title {
        font-size: 0.98rem;
    }

    .progress-card-top,
    .focus-top,
    .profile-strip-top {
        flex-direction: column;
        align-items: flex-start;
    }

    .focus-top,
    .profile-strip-top {
        gap: 0.45rem;
    }

    .challenge-progress-row {
        flex-wrap: wrap;
        padding: 0.62rem 0.66rem;
        gap: 0.48rem;
    }

    .challenge-progress-index {
        min-width: 30px;
        width: 30px;
        height: 30px;
        font-size: 0.76rem;
    }

    .challenge-progress-category {
        min-width: 0;
        font-size: 0.64rem;
        padding: 0.28rem 0.42rem;
    }

    .challenge-progress-text {
        width: 100%;
        font-size: 0.88rem;
        line-height: 1.5;
    }

    .focus-position {
        font-size: 0.72rem;
    }

    .status-chip,
    .current-category-chip,
    .metric-pill {
        font-size: 0.74rem;
    }

    .status-chip {
        padding: 0.38rem 0.7rem;
    }

    .metric-row {
        gap: 0.4rem;
    }

    .metric-pill {
        flex: 1 1 100%;
        padding: 0.48rem 0.68rem;
    }

    .profile-strip-meta,
    .compact-meta,
    .compact-main,
    .focus-text,
    .panel-value,
    .subtle-text {
        word-break: break-word;
    }

    .stButton > button {
        min-height: 2.82rem;
        font-size: 0.9rem;
        border-radius: 14px;
    }

    .stButton > button[kind="primary"],
    .stButton > button[kind="secondary"] {
        min-height: 3rem;
        font-size: 0.96rem;
    }

    .metric-pill {
        border-radius: 10px;
    }

    div[data-testid="stForm"] {
        max-width: none;
        padding: 0.82rem 0.82rem 0.2rem 0.82rem;
        border-radius: 16px;
    }

    div[data-testid="stRadio"] {
        max-width: none;
    }

    .auth-title {
        max-width: none;
        font-size: 0.98rem;
        margin-bottom: 0.62rem;
    }

    div[data-testid="stFormSubmitButton"] > button,
    .stForm [data-testid="stFormSubmitButton"] > button {
        min-height: 2.95rem !important;
        font-size: 0.96rem !important;
    }

    .stForm .stButton > button {
        width: 100%;
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

    meta_col, logout_col = st.columns([7.2, 1], gap="small")
    with meta_col:
        st.markdown(profile_html, unsafe_allow_html=True)
    with logout_col:
        if st.button("Se déconnecter", use_container_width=True, type="tertiary"):
            st.session_state.logged_profile_slug = None
            clear_profile_session()
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
    requires_photo = challenge_requires_photo(current_item)
    photo_chip_html = '<div class="status-chip">Preuve photo requise</div>' if requires_photo else ""

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
        f"{photo_chip_html}"
        '</div>'
        '</div>'
    )

    st.markdown(current_html, unsafe_allow_html=True)

    if progress["status"] in ["todo", "redo"]:
        challenge_id = int(current_item["id"])
        c_done, c_joker = st.columns([1.12, 1], gap="small")

        if requires_photo:
            uploaded_file = st.file_uploader(
                "Photo de preuve",
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=False,
                key=f"proof_{profile['slug']}_{challenge_id}",
                help="Une photo est obligatoire pour envoyer ce défi en validation.",
            )
            if uploaded_file is not None:
                st.image(uploaded_file, caption="Aperçu de la photo", use_container_width=True)

            with c_done:
                if st.button(
                    "Envoyer la photo",
                    key=f"submit_photo_{profile['slug']}_{challenge_id}",
                    use_container_width=True,
                    type="primary",
                    disabled=uploaded_file is None,
                ):
                    ok, message = save_photo_submission(profile["slug"], challenge_id, uploaded_file)
                    if ok:
                        set_global_state(profile["slug"], int(progress["challenge_index"]), "pending")
                        st.rerun()
                    st.error(message)
        else:
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
                if get_challenge_feature_status()["submissions_table"]:
                    delete_submission(profile["slug"], challenge_id)
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
    profiles = get_profiles()
    if not profiles:
        st.subheader("Espace personnel")
        st.warning("Aucun profil.")
        return

    profiles_map = {p["slug"]: p for p in profiles}

    if (
        st.session_state.logged_profile_slug is not None
        and st.session_state.logged_profile_slug not in profiles_map
    ):
        st.session_state.logged_profile_slug = None

    if st.session_state.logged_profile_slug is None:
        st.markdown('<div class="auth-title">Espace personnel</div>', unsafe_allow_html=True)
        with st.form("user_login_form"):
            pseudo = st.text_input("Pseudo")
            pin = st.text_input("Code PIN", type="password")
            submitted = st.form_submit_button("Entrer", use_container_width=True, type="primary")

        if submitted:
            profile = find_profile_by_login_input(pseudo, profiles)
            if profile is not None and verify_pin(pin, profile["pin"]):
                maybe_upgrade_profile_pin(profile["slug"], pin, profile["pin"])
                st.session_state.logged_profile_slug = profile["slug"]
                persist_profile_session(profile["slug"])
                st.rerun()
            else:
                st.error("Identifiants incorrects.")
        return

    st.subheader("Espace personnel")
    profile = profiles_map[st.session_state.logged_profile_slug]
    current_item, progress, items = current_challenge(profile["slug"])
    completed_count = get_completed_count(profile["slug"])

    render_current_challenge(profile, current_item, progress, items, completed_count)
    st.markdown("<div style='height:0.45rem;'></div>", unsafe_allow_html=True)
    render_user_progress_summary(items, progress, completed_count)
    st.markdown("<div style='height:0.45rem;'></div>", unsafe_allow_html=True)
    render_master_list(items, progress)


def render_admin_area():
    if not st.session_state.admin_ok:
        st.markdown('<div class="auth-title">Espace admin</div>', unsafe_allow_html=True)
        with st.form("admin_login_form"):
            password = st.text_input("Mot de passe admin", type="password")
            submitted = st.form_submit_button("Connexion admin", use_container_width=True, type="primary")

        if submitted:
            if password == ADMIN_PASSWORD:
                st.session_state.admin_ok = True
                persist_admin_session()
                st.rerun()
            else:
                st.error("Mot de passe incorrect.")
        return

    st.subheader("Espace admin")
    top1, _ = st.columns([1, 4])
    with top1:
        if st.button("Quitter", use_container_width=True):
            st.session_state.admin_ok = False
            clear_admin_session()
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
                submission = None
                if challenge_requires_photo(current_item):
                    submission = get_submission(profile["slug"], int(current_item["id"]))
                    if submission is None:
                        continue
                pending_items.append(
                    {
                        "profile_slug": profile["slug"],
                        "profile_name": profile["name"],
                        "category": current_item["category"],
                        "challenge_id": int(current_item["id"]),
                        "challenge_index": idx,
                        "text": current_item["text"],
                        "requires_photo": challenge_requires_photo(current_item),
                        "submission": submission,
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
                        (
                            f'Défi {item["challenge_index"] + 1}/{len(all_challenges)} • '
                            + ("Preuve photo jointe" if item["requires_photo"] else "Sans preuve photo")
                        ),
                    ),
                    unsafe_allow_html=True,
                )

                if item["requires_photo"] and item["submission"] is not None:
                    photo_bytes, photo_error = download_submission_photo(item["submission"])
                    if photo_error:
                        st.warning(photo_error)
                    elif photo_bytes:
                        st.image(photo_bytes, caption="Preuve photo", use_container_width=True)
                        st.download_button(
                            "Télécharger la photo",
                            data=photo_bytes,
                            file_name=item["submission"].get("photo_filename") or f"preuve-{item['challenge_id']}.jpg",
                            mime=item["submission"].get("photo_mime_type") or "image/jpeg",
                            key=f"download_{item['profile_slug']}_{item['challenge_id']}",
                            use_container_width=True,
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

                        if get_challenge_feature_status()["submissions_table"]:
                            delete_submission(item["profile_slug"], item["challenge_id"])
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
                        if get_challenge_feature_status()["submissions_table"]:
                            delete_submission(item["profile_slug"], item["challenge_id"])
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
        feature_status = get_challenge_feature_status()

        st.markdown(
            build_panel_html("Nombre de défis", str(len(items)), "Dans cette catégorie"),
            unsafe_allow_html=True,
        )

        if not is_photo_feature_ready():
            st.info(get_photo_feature_setup_message())

        st.markdown("### Nouveau défi")
        with st.form(f"add_challenge_form_{category}"):
            new_challenge = st.text_area("Texte", key=f"new_{category}", height=120)
            new_requires_photo = st.checkbox(
                "Preuve photo demandée",
                key=f"new_requires_photo_{category}",
                disabled=not feature_status["requires_photo_column"],
            )
            add_submitted = st.form_submit_button("Ajouter le défi", use_container_width=True)

        impacted_profiles = count_profiles_impacted_by_insert(
            get_category_insert_index(category),
            len(all_challenges),
        )
        if impacted_profiles:
            st.info(
                f"L'ajout dans cette catégorie renverra {impacted_profiles} profil(s) actif(s) vers ce nouveau défi."
            )
        if add_submitted:
            ok, message = add_challenge(category, new_challenge, new_requires_photo)
            if ok:
                st.success(message)
                st.rerun()
            else:
                st.error(message)

        st.markdown("### Classement des défis")

        if not items:
            st.info("Aucun défi dans cette catégorie.")
        else:
            if sort_items is None:
                st.warning("Le drag-and-drop sera actif après installation de `streamlit-sortables`.")
            else:
                sortable_style = """
                .sortable-component { background: transparent; padding: 0; }
                .sortable-container { background: transparent; padding: 0; }
                .sortable-container-header { display: none; }
                .sortable-container-body { background: transparent; padding: 0; }
                .sortable-item, .sortable-item:hover {
                    background: rgba(255,255,255,0.94);
                    border: 1px solid #E7D9D0;
                    border-radius: 14px;
                    padding: 0.8rem 0.9rem;
                    color: #2A1318;
                    font-weight: 600;
                    margin-bottom: 0.45rem;
                    box-shadow: 0 10px 22px rgba(54, 25, 31, 0.03);
                }
                """
                sortable_labels = [
                    f"{item['id']} • {'📷 ' if challenge_requires_photo(item) else ''}{short_text(item['text'], 95)}"
                    for item in items
                ]
                sorted_labels = sort_items(sortable_labels, custom_style=sortable_style)
                sorted_ids = [int(label.split(" • ", 1)[0]) for label in sorted_labels]
                if sorted_ids != [item["id"] for item in items]:
                    st.caption("Le nouvel ordre est prêt. Clique sur le bouton ci-dessous pour l'enregistrer.")
                    if st.button("Enregistrer le nouvel ordre", key=f"save_order_{category}", use_container_width=True):
                        ok, message = save_challenge_order(category, sorted_ids)
                        if ok:
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)

        st.markdown("### Modifier un défi")
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
                        f"{i + 1}. {'[Photo] ' if challenge_requires_photo(item) else ''}{short_text(item['text'], 90)}"
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
                edited_requires_photo = st.checkbox(
                    "Preuve photo demandée",
                    value=challenge_requires_photo(selected_item),
                    key=f"edit_requires_photo_{category}_{selected_id}",
                    disabled=not feature_status["requires_photo_column"],
                )

                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Enregistrer", key=f"save_{category}", use_container_width=True):
                        ok, message = update_challenge(selected_item["id"], edited_text, edited_requires_photo)
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
            submitted = st.form_submit_button("Créer", use_container_width=True)

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
