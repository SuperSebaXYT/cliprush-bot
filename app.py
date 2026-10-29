import base64
import json
import os
from datetime import datetime, timezone, timedelta

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

tab_sources, tab_settings, tab_runs, tab_auth = st.tabs(["📺 Źródła", "⚙️ Ustawienia", "📊 Uruchomienia", "🔑 Token YouTube"]) 

with tab_auth:
    st.subheader("Autoryzacja nowego kanału YouTube")
    st.warning("Nie udostępniaj Client Secret ani wygenerowanego tokenu. W tym panelu token jest wyświetlany tylko po wymianie kodu OAuth.")
    st.write("Ta metoda działa w przeglądarce telefonu. W Google Cloud utwórz klienta OAuth typu **Aplikacja internetowa** i ustaw dokładny URI przekierowania na adres tej aplikacji Streamlit, z ukośnikiem na końcu, np. `https://twoja-aplikacja.streamlit.app/`. Ten sam adres wpisz poniżej.")
    with st.form("youtube_oauth_start"):
        oauth_client_id = st.text_input("OAuth Client ID", key="oauth_client_id")
        oauth_client_secret = st.text_input("OAuth Client Secret", type="password", key="oauth_client_secret")
        oauth_redirect_uri = st.text_input("Redirect URI aplikacji Streamlit", key="oauth_redirect_uri", placeholder="https://twoja-aplikacja.streamlit.app/")
        start_oauth = st.form_submit_button("Utwórz link logowania Google")
    if start_oauth:
        if not oauth_client_id.strip() or not oauth_client_secret.strip() or not oauth_redirect_uri.startswith("https://"):
            st.error("Wpisz Client ID, Client Secret i pełny HTTPS Redirect URI.")
        else:
            import secrets as _secrets
            st.session_state["oauth_state"] = _secrets.token_urlsafe(24)
            st.session_state["oauth_client_id_saved"] = oauth_client_id.strip()
            st.session_state["oauth_client_secret_saved"] = oauth_client_secret.strip()
            st.session_state["oauth_redirect_uri_saved"] = oauth_redirect_uri.strip()
            from urllib.parse import urlencode
            params = {
                "client_id": oauth_client_id.strip(),
                "redirect_uri": oauth_redirect_uri.strip(),
                "response_type": "code",
                "scope": "https://www.googleapis.com/auth/youtube.upload",
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "state": st.session_state["oauth_state"],
            }
            auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
            st.link_button("Zaloguj się na konto nowego kanału", auth_url, use_container_width=True)
            st.caption("Po zatwierdzeniu Google wróci do tej aplikacji. Nie zamykaj karty panelu.")

    callback_code = st.query_params.get("code", "")
    callback_state = st.query_params.get("state", "")
    if callback_code:
        st.info("Google zwrócił kod autoryzacyjny. Sprawdź, czy stan zgadza się z tym zapisanym przy tworzeniu linku.")
        expected_state = st.session_state.get("oauth_state", "")
        if expected_state and callback_state and callback_state == expected_state:
            st.success("Kontrola state zakończona powodzeniem.")
        else:
            st.error("Nie można potwierdzić sesji OAuth w tym panelu. Wróć do zakładki Token YouTube i utwórz link ponownie w tej samej sesji przeglądarki.")
        st.text_input("Kod OAuth z adresu strony", value=callback_code, key="oauth_callback_code")

    if st.session_state.get("oauth_client_id_saved") and st.session_state.get("oauth_client_secret_saved") and st.session_state.get("oauth_redirect_uri_saved"):
        with st.form("youtube_oauth_exchange"):
            auth_code = st.text_input("Kod autoryzacyjny (wypełniony automatycznie po powrocie z Google)", value=st.query_params.get("code", ""))
            exchange = st.form_submit_button("Wygeneruj token")
        if exchange:
            if not auth_code.strip():
                st.error("Brakuje kodu autoryzacyjnego. Najpierw zaloguj się przez link Google.")
            elif st.query_params.get("state", "") != st.session_state.get("oauth_state", ""):
                st.error("Nie zgadza się parametr state. Utwórz nowy link logowania i dokończ proces w tej samej sesji.")
            else:
                try:
                    token_response = requests.post(
                        "https://oauth2.googleapis.com/token",
                        data={
                            "code": auth_code.strip(),
                            "client_id": st.session_state["oauth_client_id_saved"],
                            "client_secret": st.session_state["oauth_client_secret_saved"],
                            "redirect_uri": st.session_state["oauth_redirect_uri_saved"],
                            "grant_type": "authorization_code",
                        }, timeout=30)
                    if not token_response.ok:
                        st.error(f"Google odrzucił wymianę kodu ({token_response.status_code}). Sprawdź typ klienta i identyczny Redirect URI.")
                    else:
                        tok = token_response.json()
                        if not tok.get("refresh_token"):
                            st.error("Google nie zwrócił refresh_token. Utwórz link ponownie; sprawdź access_type=offline i prompt=consent.")
                        else:
                            token_json = {
                                "token": tok.get("access_token"),
                                "refresh_token": tok.get("refresh_token"),
                                "token_uri": "https://oauth2.googleapis.com/token",
                                "expiry": (datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 3600)))).isoformat().replace("+00:00", "Z"),
                                "client_id": st.session_state["oauth_client_id_saved"],
                                "client_secret": st.session_state["oauth_client_secret_saved"],
                                "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
                                "universe_domain": "googleapis.com",
                            }
                            st.success("Token utworzony. Skopiuj poniższy JSON i wklej go do GitHub Secret YOUTUBE_TOKEN_JSON.")
                            st.code(json.dumps(token_json, indent=2), language="json")
                            st.warning("To pełny dostęp do publikowania na Twoim kanale. Nie udostępniaj JSON-u i nie zapisuj go w repozytorium.")
                except Exception as exc:
                    st.error(f"Nie udało się połączyć z Google: {exc}")

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
        st.divider()
        st.subheader("Automatyczny wybór VOD-ów")
        auto_discovery = st.toggle("Automatycznie wyszukuj najnowsze VOD-y", value=bool(config.get("auto_discovery_enabled", True)))
        discovery_channels_text = st.text_area(
            "Kanały YouTube, po jednym URL na linię",
            value="\n".join(config.get("discovery_channels", [
                "https://www.youtube.com/@IShowSpeed/videos",
                "https://www.youtube.com/@KaiCenat/videos",
                "https://www.youtube.com/@CaseOh_/videos",
            ])),
            height=110,
        )
        scan_per_channel = st.slider("Ile najnowszych filmów sprawdzać z każdego kanału", 5, 50,
                                     int(config.get("discovery_scan_per_channel", 30)), step=5)
        max_age_days = st.slider("Maksymalny wiek VOD-a (dni)", 1, 90, int(config.get("max_source_age_days", 30)))
        min_source_minutes = st.slider("Minimalna długość źródła (minuty)", 5, 60,
                                       max(5, int(config.get("min_source_duration_seconds", 600)) // 60))
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
        if publish and not cleaned and not auto_discovery:
            st.error("Włącz automatyczne wyszukiwanie albo dodaj źródła dozwolone do ponownej publikacji.")
        else:
            new_config = dict(config)
            new_config.update({
                "clips_per_source": clips_per_source,
                "clip_duration_seconds": duration,
                "min_clip_seconds": min(20, duration),
                "max_clip_seconds": min(55, duration),
                "max_sources_per_run": max_sources,
                "auto_discovery_enabled": auto_discovery,
                "discovery_channels": [x.strip() for x in discovery_channels_text.splitlines()
                                        if x.strip() and not x.strip().startswith("#")],
                "discovery_scan_per_channel": scan_per_channel,
                "max_source_age_days": max_age_days,
                "min_source_duration_seconds": min_source_minutes * 60,
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
st.write(f"Ręczne źródła: **{len(cleaned)}** · Auto-discovery: **{'włączone' if config.get('auto_discovery_enabled', False) else 'wyłączone'}** · Klipów na źródło: **{config.get('clips_per_source', 2)}**")
if st.button("🚀 Zapisz najpierw ustawienia, potem uruchom bota", type="primary", key="run_bot"):
    try:
        # Prevent dispatch when there are no source URLs.
        current_sources, _ = read_file("sources.txt")
        has_manual = bool([x for x in current_sources.splitlines() if x.strip() and not x.strip().startswith("#")])
        if not has_manual and not config.get("auto_discovery_enabled", False):
            st.error("Włącz automatyczne wyszukiwanie w Ustawieniach albo dodaj adres VOD.")
        else:
            trigger_workflow()
            st.success("Wysłano żądanie uruchomienia. Sprawdź zakładkę Uruchomienia za chwilę.")
    except Exception as exc:
        st.error(str(exc))

st.caption("ClipRush Mobile · panel steruje GitHub Actions; renderowanie odbywa się w runnerze GitHub.")
