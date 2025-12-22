# revolutx-telegram-momentum-bot

Bot Telegram in Python che **NON esegue trading**: legge (read-only) dati da Revolut X API per generare **segnali quantitativi** (momentum intraday) e gestire la regola operativa **09:00–20:00 (Europe/Rome)** con **alert “chiudi tutto”** e **recap alle 20:00**.

## Cosa fa (in breve)

- **Read-only**: nessun ordine, nessun trading automatico.
- **Scanner**: ogni 60s (configurabile) legge pairs + candele 5m e calcola momentum 1h/15m.
- **Segnali BUY**: quando supera soglie (dipendono da `risk_mode`).
- **Exit alert** (per posizioni registrate manualmente):
  - trailing stop aggressivo (peak − trailing%)
  - reversal 15m (best-effort)
- **Regola “chiudi entro le 20”**:
  - 19:55 (configurabile) → “CHIUDI TUTTO ORA” se ci sono posizioni aperte
  - 20:00 → recap + alert emergenza se ci sono posizioni ancora aperte
- **Tracking manuale**:
  - `/setcapital` capitale iniziale
  - `/buy` e `/sell` per registrare operazioni manuali
  - `/portfolio` per posizioni + PnL stimato
- **Single user**: allowlist su `TELEGRAM_ALLOWED_CHAT_ID`

## File principali

- `bot/main.py`: bot Telegram + scheduling + comandi
- `bot/revolutx.py`: client HTTP Revolut X (requests, timeout, retry) + endpoint centralizzati
- `bot/strategy.py`: momentum intraday
- `bot/storage.py`: SQLite (`bot.db`) per settings/trades/positions
- `bot/config.py`: config via env + profili rischio

## Variabili ambiente (ENV VARS)

Obbligatorie:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_ID` (opzionale: se mancante, il primo `/start` diventa owner e viene salvato nel DB)

Consigliate:

- `TZ` (default `Europe/Rome`)
- `REVOLUTX_BASE_URL` (default `https://api.revolut.com`)
- `REVOLUTX_BASE_PATH` (default `/revolutx`)
- `REVOLUTX_API_KEY` (opzionale, se la doc prevede autenticazione read-only)
- `REVOLUTX_TIMEOUT_SECONDS` (default `10`)
- `SCAN_INTERVAL_SECONDS` (default `60`)
- `PAIRS_LIMIT` (default `50`)
- `SIGNAL_COOLDOWN_SECONDS` (default `1800`)
- `HARD_CLOSE_MINUTE` (default `55`, quindi 19:55)
- `DB_PATH` (default `bot.db`)
- `STATUS_PING_MINUTES` (default `30`) → recap “stato bot” periodico
- `STATUS_PING_ALWAYS` (default `0`) → se `1` manda lo status anche fuori 09:00–20:00
- `ENABLE_WEB_SETUP` (default `0`) → se `1` avvia il wizard web
- `SETUP_ADMIN_TOKEN` (obbligatorio se `ENABLE_WEB_SETUP=1`) → token admin per proteggere la pagina
- `WEB_PORT` (default `8080`, su alcuni provider usa `PORT`)
- `WEB_HOST` (default `0.0.0.0`)

## Endpoints Revolut X (IMPORTANTE)

Revolut X può cambiare path/shape delle risposte.

- La base è configurabile via `REVOLUTX_BASE_URL` + `REVOLUTX_BASE_PATH`
- I path specifici sono centralizzati in `bot/revolutx.py` dentro `RevolutXEndpoints`

Se i segnali non arrivano o `get_pairs()` restituisce lista vuota, quasi certamente devi aggiornare:

- `RevolutXEndpoints.pairs`
- `RevolutXEndpoints.candles`
- `RevolutXEndpoints.ticker`
- parsing delle risposte (già scritto in modo “tollerante”, ma potrebbe servire adattamento)

## Comandi Telegram

- `/start` stato rapido
- `/setup` setup guidato (stile “registration page” in chat)
- `/status` stato e diagnostica (scanner/ultimi scan/notifiche)
- `/setcapital 100 EUR`
- `/setrisk aggressive|normal|conservative`
- `/buy BTC-EUR 20 at 43000`
- `/sell BTC-EUR 20 at 43000`
- `/portfolio`
- `/config`
- `/pause` / `/resume`
- `/reset` (con conferma via bottoni)

## Deploy (consigliato: Render / Railway / Fly.io / VPS)

### Docker (qualsiasi provider)

Build:

```bash
docker build -t revolutx-telegram-momentum-bot .
```

Run:

```bash
docker run --rm \
  -e TELEGRAM_BOT_TOKEN="..." \
  -e TELEGRAM_ALLOWED_CHAT_ID="123456789" \
  -e TZ="Europe/Rome" \
  -e REVOLUTX_BASE_URL="https://api.revolut.com" \
  -e REVOLUTX_BASE_PATH="/revolutx" \
  revolutx-telegram-momentum-bot
```

### Render (Background Worker)

- **Type**: Background Worker
- **Build command**: `pip install -r requirements.txt`
- **Start command**: `python -m bot.main`
- **Env vars**: inserisci quelle sopra

## Wizard Web (frontend + server)

Se vuoi configurare tutto da browser (senza comandi), abilita il wizard web:

ENV:

- `ENABLE_WEB_SETUP=1`
- `SETUP_ADMIN_TOKEN=<una stringa lunga e segreta>`

Poi apri (sul dominio del tuo servizio):

- `/setup?token=<SETUP_ADMIN_TOKEN>`

Nota:

- I segreti **non** si inseriscono nella pagina: `TELEGRAM_BOT_TOKEN` e (se serve) `REVOLUTX_API_KEY` restano solo ENV.

## Come ottenere `TELEGRAM_ALLOWED_CHAT_ID` in 30 secondi

Opzioni semplici:

- Scrivi a `@userinfobot` su Telegram → ti mostra il tuo `id`.
- Se vuoi usare una chat privata col tuo bot: manda un messaggio al bot e usa l’API Telegram `getUpdates` (metodo più “tecnico”).

## Note su limiti e responsabilità

- Questo bot **non può sapere** se una coin farà pump/dump.
- I segnali sono quantitativi (momentum/volatilità implicita via momentum), con stop aggressivi e regola “chiudi entro le 20”.
- Il bot **non può chiudere posizioni**: invia solo alert.

