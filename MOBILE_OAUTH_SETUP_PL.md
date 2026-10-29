# Token YouTube przez telefon (ClipRush)

1. W Google Cloud wybierz projekt, włącz YouTube Data API v3 i skonfiguruj ekran zgody OAuth. Dodaj swoje konto jako użytkownika testowego, jeśli aplikacja jest w trybie testowym.
2. Utwórz klienta OAuth typu **Aplikacja internetowa**. W `Autoryzowane identyfikatory URI przekierowania` wpisz dokładny publiczny adres aplikacji Streamlit, np. `https://NAZWA.streamlit.app/` (z końcowym `/`). Nie używaj adresu przykładowego, tylko prawdziwy URL swojej aplikacji.
3. Otwórz panel ClipRush w tej samej przeglądarce telefonu i wybierz kartę **Token YouTube**.
4. Wpisz Client ID, Client Secret oraz dokładnie ten sam Redirect URI. Utwórz link logowania i otwórz go.
5. Zaloguj się na konto Google zarządzające nowym kanałem i zaakceptuj uprawnienie `youtube.upload`. Po powrocie do panelu wybierz „Wygeneruj token”.
6. Skopiuj wygenerowany JSON. W GitHub repozytorium otwórz Settings → Secrets and variables → Actions → New repository secret. Nazwa: `YOUTUBE_TOKEN_JSON`; wartość: cały JSON.

## Bezpieczeństwo i ograniczenia

- Nigdy nie umieszczaj Client Secret ani tokenu w repozytorium, issue ani czacie.
- Jeśli aplikacja Streamlit uruchomi nową sesję po przekierowaniu i zgubi stan OAuth, proces celowo przerwie się. Wtedy uruchom link ponownie w tej samej karcie/sesji.
- Jeśli Google nie zwróci `refresh_token`, ponów autoryzację z `prompt=consent` i `access_type=offline` (panel ustawia je automatycznie).
- Nie publikuj automatycznie materiałów, do których nie masz praw.
