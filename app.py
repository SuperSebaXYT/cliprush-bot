import base64
import json

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
:root {
    color-scheme: dark;
}
.stApp {
    background:
        radial-gradient(ellipse at 12% 5%, rgba(124, 35, 255, .22), transparent 38%),
        radial-gradient(ellipse at 95% 28%, rgba(0, 205, 255, .13), transparent 34%),
        linear-gradient(145deg, #080711 0%, #10091f 48%, #070b16 100%);
    color: #F5F3FF;
}
.block-container {
    max-width: 760px;
    padding-top: 1.1rem;
    padding-bottom: 3rem;
}
h1 {
    letter-spacing: -0.05em;
    background: linear-gradient(90deg, #ffffff 10%, #c084fc 58%, #22d3ee 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
h2, h3, label, p, span {
    color: #eee9ff;
}
div[data-testid="stVerticalBlockBorderWrapper"],
div[data-testid="stExpander"],
div[data-testid="stTabs"] [data-baseweb="tab-panel"] {
    background: rgba(18, 13, 34, .72);
    border-color: rgba(139, 92, 246, .22);
    border-radius: 16px;
}
div[data-testid="stTextInput"] input,
div[data-testid="stTextArea"] textarea,
div[data-baseweb="select"] > div,
div[data-baseweb="input"] > div {
    background: #090815 !important;
    color: #F5F3FF !important;
    border: 1px solid #40305f !important;
    border-radius: 11px !important;
}
div[data-testid="stTextArea"] textarea::placeholder,
div[data-testid="stTextInput"] input::placeholder {
    color: #827796 !important;
}
div[data-testid="stSlider"] [role="slider"] {
    background: #a855f7;
}
div.stButton > button,
div.stFormSubmitButton > button,
div[data-testid="stLinkButton"] a {
    width: 100%;
    min-height: 3rem;
    border-radius: 12px;
    font-weight: 700;
    border: 1px solid rgba(168, 85, 247, .55);
    background: linear-gradient(105deg, #6d28d9, #7c3aed 55%, #0891b2);
    color: white;
}
div.stButton > button:hover,
div.stFormSubmitButton > button:hover {
    border-color: #22d3ee;
    color: white;
    filter: brightness(1.12);
}
div[data-testid="stMetric"] {
    background: linear-gradient(135deg, #17102b, #0d1828);
    border: 1px solid rgba(139, 92, 246, .25);
    padding: 12px;
    border-radius: 12px;
}
div[data-testid="stMetricValue"] {
    color: #c084fc;
}
div[data-testid="stTabs"] button[aria-selected="true"] {
    color: #c084fc;
    border-bottom-color: #a855f7;
}
hr {
    border-color: rgba(139, 92, 246, .22);
}
.small-note {
    opacity: .75;
    font-size: .9rem;
}
</style>
""", unsafe_allow_html=True)

st.title("🎬 ClipRush Mobile")
st.caption("Panel sterowania AI Clipping Botem · wersja 1.2")
st.markdown("Zarządzaj źródłami, ustawieniami i uruchomieniami z telefonu.")

if not TOKEN or not REPO or "/" not in REPO:
    st.error("Brakuje konfiguracji Secrets w Streamlit Cloud.")
    st.code(
        'GITHUB_TOKEN = "github_pat_..."\n'
        'GITHUB_REPO = "SuperSebaXYT/cliprush-bot"\n'
        'GITHUB_BRANCH = "main"'
    )
    st.info(
        "Dodaj te wartości w ustawieniach aplikacji "
        "Streamlit Cloud → Secrets."
    )
    st.stop()

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def api_get(path, params=None):
    response = requests.get(
        f"{API}/repos/{REPO}/{path}",
        headers=HEADERS,
        params=params,
        timeout=25,
    )

    if not response.ok:
        raise RuntimeError(
            f"GitHub API error {response.status_code}: "
            f"{response.text[:400]}"
        )

    return response.json()


def read_file(path):
    try:
        data = api_get(
            f"contents/{path}",
            params={"ref": BRANCH},
        )

        raw = base64.b64decode(
            data["content"]
        ).decode("utf-8")

        return raw, data["sha"]

    except RuntimeError as exc:
        if "404" in str(exc):
            return "", None
        raise


def write_file(path, content, sha, message):
    body = {
        "message": message,
        "content": base64.b64encode(
            content.encode("utf-8")
        ).decode("ascii"),
        "branch": BRANCH,
    }

    if sha:
        body["sha"] = sha

    response = requests.put(
        f"{API}/repos/{REPO}/contents/{path}",
        headers=HEADERS,
        json=body,
        timeout=25,
    )

    if not response.ok:
        raise RuntimeError(
            f"Nie udało się zapisać {path}: "
            f"{response.status_code} "
            f"{response.text[:350]}"
        )

    return response.json()


def trigger_workflow():
    url = (
        f"{API}/repos/{REPO}/actions/"
        "workflows/clipping.yml/dispatches"
    )

    response = requests.post(
        url,
        headers=HEADERS,
        json={"ref": BRANCH},
        timeout=25,
    )

    if response.status_code not in (204, 200):
        raise RuntimeError(
            f"Nie udało się uruchomić workflow: "
            f"{response.status_code} "
            f"{response.text[:350]}"
        )


def recent_runs():
    data = api_get(
        "actions/workflows/clipping.yml/runs",
        params={"per_page": 5},
    )

    return data.get("workflow_runs", [])


def clean_urls(text):
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip()
        and not line.strip().startswith("#")
    ]


def save_sources_and_config(
    urls,
    config,
    sources_sha,
    config_sha,
):
    source_content = urls.rstrip() + "\n"

    write_file(
        "sources.txt",
        source_content,
        sources_sha,
        "Update authorized clipping sources",
    )

    write_file(
        "config.json",
        json.dumps(
            config,
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        config_sha,
        "Update clipping settings",
    )


try:
    config_text, config_sha = read_file("config.json")
    sources_text, sources_sha = read_file("sources.txt")

    if not config_text:
        raise RuntimeError(
            "Nie znaleziono config.json w repozytorium."
        )

    config = json.loads(config_text)

except Exception as exc:
    st.error(f"Nie mogę odczytać repozytorium: {exc}")
    st.stop()


with st.container(border=True):
    st.subheader("⚡ Sterowanie")
    st.write(f"Repozytorium: `{REPO}`")
    st.write(f"Branch: `{BRANCH}`")
    st.caption(
        "Zmiany są zapisywane bezpośrednio w repozytorium GitHub."
    )


tab_sources, tab_settings, tab_runs = st.tabs([
    "📺 Źródła",
    "⚙️ Ustawienia",
    "📊 Uruchomienia",
])


with tab_sources:
    st.subheader("Źródła materiałów")

    st.caption(
        "Jeden URL na linię. Dodawaj wyłącznie materiały, "
        "które masz prawo pobierać i ponownie publikować."
    )

    urls = st.text_area(
        "Lista adresów",
        value=sources_text,
        height=230,
        placeholder="https://...\nhttps://...",
        label_visibility="collapsed",
        key="source_urls",
    )

    cleaned = clean_urls(urls)

    st.metric("Aktywne adresy", len(cleaned))

    if st.button(
        "💾 Zapisz źródła",
        key="save_sources",
    ):
        try:
            write_file(
                "sources.txt",
                urls.rstrip() + "\n",
                sources_sha,
                "Update authorized clipping sources",
            )

            st.success("Zapisano źródła.")
            st.rerun()

        except Exception as exc:
            st.error(str(exc))


with tab_settings:
    st.subheader("Ustawienia klipów")

    with st.form("settings_form"):
        clips_per_source = st.slider(
            "Klipy na źródło",
            1,
            5,
            int(config.get("clips_per_source", 2)),
        )

        duration = st.slider(
            "Docelowa długość klipu (sekundy)",
            20,
            55,
            int(config.get("clip_duration_seconds", 35)),
        )

        max_sources = st.slider(
            "Maksymalna liczba źródeł na uruchomienie",
            1,
            5,
            int(config.get("max_sources_per_run", 2)),
        )

        st.divider()
        st.subheader("Automatyczne wyszukiwanie")

        auto_discovery = st.toggle(
            "Automatycznie wyszukuj LIVE i VOD-y",
            value=bool(
                config.get("auto_discovery_enabled", True)
            ),
        )

        default_channels = [
            "https://www.youtube.com/@IShowSpeed",
            "https://www.youtube.com/@KaiCenat",
            "https://www.youtube.com/@CaseOh_",
        ]

        discovery_channels_text = st.text_area(
            "Kanały YouTube, po jednym URL na linię",
            value="\n".join(
                config.get(
                    "discovery_channels",
                    default_channels,
                )
            ),
            height=110,
        )

        scan_per_channel = st.slider(
            "Ile materiałów sprawdzać z każdego kanału",
            5,
            50,
            int(config.get("discovery_scan_per_channel", 30)),
            step=5,
        )

        max_age_days = st.slider(
            "Maksymalny wiek VOD-a (dni)",
            1,
            90,
            int(config.get("max_source_age_days", 30)),
        )

        min_source_minutes = st.slider(
            "Minimalna długość źródła (minuty)",
            5,
            60,
            max(
                5,
                int(
                    config.get(
                        "min_source_duration_seconds",
                        600,
                    )
                ) // 60,
            ),
        )

        live_capture_minutes = st.slider(
            "Czas nagrywania LIVE (minuty)",
            2,
            60,
            max(
                2,
                int(
                    config.get(
                        "live_capture_seconds",
                        480,
                    )
                ) // 60,
            ),
        )

        st.divider()
        st.subheader("Transkrypcja")

        language_options = ["en", "pl", "auto"]
        current_language = config.get("language", "en")

        language = st.selectbox(
            "Język transkrypcji",
            language_options,
            index=(
                language_options.index(current_language)
                if current_language in language_options
                else 0
            ),
        )

        model_options = ["base", "small", "medium"]
        current_model = config.get("whisper_model", "small")

        model = st.selectbox(
            "Model Whisper",
            model_options,
            index=(
                model_options.index(current_model)
                if current_model in model_options
                else 1
            ),
        )

        st.divider()
        st.subheader("YouTube")

        publish = st.toggle(
            "Automatycznie publikuj na YouTube",
            value=bool(config.get("publish", False)),
        )

        privacy_options = [
            "private",
            "unlisted",
            "public",
        ]

        current_privacy = config.get(
            "privacy_status",
            "private",
        )

        privacy = st.selectbox(
            "Widoczność",
            privacy_options,
            index=(
                privacy_options.index(current_privacy)
                if current_privacy in privacy_options
                else 0
            ),
        )

        title_prefix = st.text_input(
            "Początek tytułu",
            value=config.get("title_prefix", "ClipRush"),
        )

        description = st.text_area(
            "Opis",
            value=config.get("description", ""),
        )

        tags_text = st.text_input(
            "Tagi oddzielone przecinkami",
            value=", ".join(config.get("tags", [])),
        )

        st.divider()

        save_settings = st.form_submit_button(
            "💾 Zapisz ustawienia",
        )

        save_and_run = st.form_submit_button(
            "🚀 Zapisz ustawienia i uruchom bota",
            type="primary",
        )

    if save_settings or save_and_run:
        new_config = dict(config)

        new_config.update({
            "clips_per_source": clips_per_source,
            "clip_duration_seconds": duration,
            "min_clip_seconds": min(20, duration),
            "max_clip_seconds": min(55, duration),
            "max_sources_per_run": max_sources,
            "auto_discovery_enabled": auto_discovery,
            "discovery_channels": [
                item.strip()
                for item in discovery_channels_text.splitlines()
                if item.strip()
                and not item.strip().startswith("#")
            ],
            "discovery_scan_per_channel": scan_per_channel,
            "max_source_age_days": max_age_days,
            "min_source_duration_seconds": (
                min_source_minutes * 60
            ),
            "live_capture_seconds": (
                live_capture_minutes * 60
            ),
            "language": language,
            "whisper_model": model,
            "publish": publish,
            "privacy_status": privacy,
            "title_prefix": title_prefix,
            "description": description,
            "tags": [
                item.strip()
                for item in tags_text.split(",")
                if item.strip()
            ],
        })

        current_urls = st.session_state.get(
            "source_urls",
            sources_text,
        )

        current_sources = clean_urls(current_urls)

        if save_and_run and not current_sources and not auto_discovery:
            st.error(
                "Włącz automatyczne wyszukiwanie "
                "albo dodaj źródła."
            )

        elif save_and_run and publish and not current_sources and not auto_discovery:
            st.error(
                "Nie można publikować bez skonfigurowanych źródeł."
            )

        else:
            try:
                save_sources_and_config(
                    current_urls,
                    new_config,
                    sources_sha,
                    config_sha,
                )

                if save_and_run:
                    trigger_workflow()

                    st.success(
                        "Zapisano ustawienia i uruchomiono pipeline."
                    )

                    st.info(
                        "Postęp sprawdzisz w zakładce Uruchomienia."
                    )

                else:
                    st.success("Zapisano ustawienia.")

                st.rerun()

            except Exception as exc:
                st.error(str(exc))

    if publish and privacy == "public":
        st.warning(
            "Publikacja publiczna jest włączona. "
            "Najpierw sprawdź jakość klipów i prawa do materiałów."
        )


with tab_runs:
    st.subheader("Ostatnie uruchomienia")

    if st.button(
        "🔄 Odśwież status",
        key="refresh_runs",
    ):
        st.rerun()

    try:
        runs = recent_runs()

        if not runs:
            st.info("Brak uruchomień.")

        for run in runs:
            status = (
                run.get("conclusion")
                or run.get("status", "unknown")
            )

            st.markdown(
                f"**{run.get('display_title', run.get('name', 'Workflow'))}**"
            )

            st.caption(
                f"{status} · "
                f"{run.get('created_at', '')} · "
                f"#{run.get('run_number', '')}"
            )

            if run.get("html_url"):
                st.link_button(
                    "Otwórz logi na GitHubie",
                    run["html_url"],
                    use_container_width=True,
                )

    except Exception as exc:
        st.error(
            f"Nie udało się pobrać uruchomień: {exc}"
        )


st.divider()

st.subheader("Status konfiguracji")

st.write(
    f"Ręczne źródła: **{len(clean_urls(st.session_state.get('source_urls', sources_text)))}**"
)

st.write(
    "Auto-discovery: **"
    + (
        "włączone"
        if config.get("auto_discovery_enabled", False)
        else "wyłączone"
    )
    + "**"
)

st.write(
    f"Klipów na źródło: **{config.get('clips_per_source', 2)}**"
)

st.caption(
    "ClipRush Mobile · panel steruje GitHub Actions. "
    "Pobieranie, transkrypcja i renderowanie odbywają się na runnerze GitHub."
)
