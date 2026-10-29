import base64
import json
import os
from datetime import datetime, timezone

import requests
import streamlit as st

st.set_page_config(
    page_title="ClipRush Mobile",
    page_icon="🎬",
    layout="centered",
    initial_sidebar_state="collapsed",
)

API = "https://api.github.com"
TOKEN = st.secrets.get("GITHUB_TOKEN", "")
REPO = st.secrets.get("GITHUB_REPO", "")
BRANCH = st.secrets.get("GITHUB_BRANCH", "main")

st.markdown("""
<style>
.block-container {max-width: 760px; padding-top: 1.1rem; padding-bottom: 3rem;}
h1 {letter-spacing: -0.04em;}
div.stButton > button {width:100%; min-height: 3rem; border-radius: 12px; font-weight: 700;}
div[data-testid="stMetric"] {background:#17172A; padding:12px; border-radius:12px;}
.small-note {opacity:.75; font-size:.9rem;}
</style>
""", unsafe_allow_html=True)

st.title("🎬 ClipRush Mobile")
st.caption("Panel sterowania AI Clipping Botem")
st.markdown("Zarządzaj źródłami, ustawieniami i uruchomieniami z telefonu.")

if not TOKEN or not REPO or "/" not in REPO:
    st.error("Brakuje konfiguracji Secrets w Streamlit Cloud.")
    st.code('GITHUB_TOKEN = "github_pat_..."\nGITHUB_REPO = "twoj-login/cliprush-bot"\nGITHUB_BRANCH = "main"')
    st.info("Dodaj te wartości w ustawieniach aplikacji Streamlit Cloud → Secrets. Nie wpisuj tokena w tym formularzu.")
    st.stop()

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

def api_get(path, params=None):
    r = requests.get(f"{API}/repos/{REPO}/{path}", headers=HEADERS, params=params, timeout=25)
    if not r.ok:
        raise RuntimeError(f"GitHub API error {r.status_code}: {r.text[:400]}")
    return r.json()

def read_file(path):
    try:
        data = api_get(f"contents/{path}", params={"ref": BRANCH})
        raw = base64.b64decode(data["content"]).decode("utf-8")
        return raw, data["sha"]
    except RuntimeError as e:
        if "404" in str(e):
            return "", None
        raise

def write_file(path, content, sha, message):
    body = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": BRANCH,
    }
    if sha:
        body["sha"] = sha
    r = requests.put(f"{API}/repos/{REPO}/contents/{path}", headers=HEADERS, json=body, timeout=25)
    if not r.ok:
        raise RuntimeError(f"Nie udało się zapisać {path}: {r.status_code} {r.text[:350]}")
    return r.json()

def trigger_workflow():
    url = f"{API}/repos/{REPO}/actions/workflows/clipping.yml/dispatches"
    r = requests.post(url, headers=HEADERS, json={"ref": BRANCH}, timeout=25)
    if r.status_code not in (204, 200):
        raise RuntimeError(f"Nie udało się uruchomić workflow: {r.status_code} {r.text[:350]}")

def recent_runs():
    data = api_get("actions/workflows/clipping.yml/runs", params={"per_page": 5})
    return data.get("workflow_runs", [])

try:
    config_text, config_sha = read_file("config.json")
    sources_text, sources_sha = read_file("sources.txt")
    if not config_text:
        raise RuntimeError("Nie znaleziono config.json w repozytorium.")
    config = json.loads(config_text)
except Exception as exc:
    st.error(f"Nie mogę odczytać repozytorium: {exc}")
    st.stop()

with st.container(border=True):
    st.subheader("⚡ Sterowanie")
    st.write(f"Repozytorium: `{REPO}`")
    st.write(f"Branch: `{BRANCH}`")
    st.caption("Zmiany zapisują się bezpośrednio w repozytorium. Nie umieszczaj tu kluczy ani prywatnych tokenów.")

tab_sources, tab_settings, tab_runs = st.tabs(["📺 Źródła", "⚙️ Ustawienia", "📊 Uruchomienia"])

with tab_sources:
    st.subheader("Źródła streamów")
    st.caption("Jeden URL VOD na linię. Dodawaj wyłącznie materiały, które masz prawo ponownie publikować.")
    urls = st.text_area(
        "Lista adresów",
        value=sources_text,
        height=230,
        placeholder="https://...\nhttps://...",
        label_visibility="collapsed",
    )
    cleaned = [line.strip() for line in urls.splitlines() if line.strip() and not line.strip().startswith("#")]
    st.metric("Aktywne adresy", len(cleaned))
    if st.button("💾 Zapisz źródła", key="save_sources"):
        try:
            write_file("sources.txt", urls.rstrip() + "\n", sources_sha, "Update authorized clipping sources")
            st.success("Zapisano źródła.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

with tab_settings:
    st.subheader("Ustawienia klipów")
    with st.form("settings_form"):
        clips_per_source = st.slider("Klipy na źródło", 1, 5, int(config.get("clips_per_source", 2)))
        duration = st.slider("Docelowa długość klipu (sekundy)", 20, 55, int(config.get("clip_duration_seconds", 35)))
        max_sources = st.slider("Maksymalna liczba źródeł na uruchomienie", 1, 5, int(config.get("max_sources_per_run", 2)))
        language = st.selectbox("Język transkrypcji", ["en", "pl", "auto"],
                                index=["en", "pl", "auto"].index(config.get("language", "en"))
                                if config.get("language", "en") in ["en", "pl", "auto"] else 0)
        model = st.selectbox("Model Whisper", ["base", "small", "medium"],
                             index=["base", "small", "medium"].index(config.get("whisper_model", "small"))
                             if config.get("whisper_model", "small") in ["base", "small", "medium"] else 1)
        st.divider()
        st.subheader("YouTube")
        publish = st.toggle("Automatycznie publikuj na YouTube", value=bool(config.get("publish", False)))
        privacy_options = ["private", "unlisted", "public"]
        privacy = st.selectbox("Widoczność", privacy_options,
                               index=privacy_options.index(config.get("privacy_status", "private"))
                               if config.get("privacy_status", "private") in privacy_options else 0)
        title_prefix = st.text_input("Początek tytułu", value=config.get("title_prefix", "ClipRush"))
        description = st.text_area("Opis", value=config.get("description", ""))
        tags_text = st.text_input("Tagi oddzielone przecinkami", value=", ".join(config.get("tags", [])))
        submitted = st.form_submit_button("💾 Zapisz ustawienia")
    if submitted:
        if publish and not cleaned:
            st.error("Najpierw dodaj źródła dozwolone do ponownej publikacji.")
        else:
            new_config = dict(config)
            new_config.update({
                "clips_per_source": clips_per_source,
                "clip_duration_seconds": duration,
                "min_clip_seconds": min(20, duration),
                "max_clip_seconds": min(55, duration),
                "max_sources_per_run": max_sources,
                "language": language,
                "whisper_model": model,
                "publish": publish,
                "privacy_status": privacy,
                "title_prefix": title_prefix,
                "description": description,
                "tags": [x.strip() for x in tags_text.split(",") if x.strip()],
            })
            try:
                write_file("config.json", json.dumps(new_config, indent=2, ensure_ascii=False) + "\n",
                           config_sha, "Update clipping settings")
                st.success("Zapisano ustawienia.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    if publish and privacy == "public":
        st.warning("Publikacja publiczna jest włączona. Najpierw sprawdź jakość klipów i prawa do materiałów.")

with tab_runs:
    st.subheader("Ostatnie uruchomienia")
    if st.button("🔄 Odśwież status", key="refresh_runs"):
        st.rerun()
    try:
        runs = recent_runs()
        if not runs:
            st.info("Brak uruchomień. Zapisz źródła i uruchom pipeline.")
        for run in runs:
            status = run.get("conclusion") or run.get("status", "unknown")
            st.markdown(f"**{run.get('display_title', run.get('name', 'Workflow'))}**")
            st.caption(f"{status} · {run.get('created_at', '')} · #{run.get('run_number', '')}")
            if run.get("html_url"):
                st.link_button("Otwórz logi na GitHubie", run["html_url"], use_container_width=True)
    except Exception as exc:
        st.error(f"Nie udało się pobrać uruchomień: {exc}")

st.divider()
st.subheader("Uruchom clipping")
st.write(f"Źródeł w liście: **{len(cleaned)}** · Klipów na źródło: **{config.get('clips_per_source', 2)}**")
if st.button("🚀 Zapisz najpierw ustawienia, potem uruchom bota", type="primary", key="run_bot"):
    try:
        # Prevent dispatch when there are no source URLs.
        current_sources, _ = read_file("sources.txt")
        if not [x for x in current_sources.splitlines() if x.strip() and not x.strip().startswith("#")]:
            st.error("Dodaj i zapisz co najmniej jeden dozwolony adres VOD.")
        else:
            trigger_workflow()
            st.success("Wysłano żądanie uruchomienia. Sprawdź zakładkę Uruchomienia za chwilę.")
    except Exception as exc:
        st.error(str(exc))

st.caption("ClipRush Mobile · panel steruje GitHub Actions; renderowanie odbywa się w runnerze GitHub.")
