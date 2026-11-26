# HeadHunter MCP Server

Security-hardened MCP server for personal use with the HeadHunter API. It can
search vacancies, read minimized resume data, track negotiations, and prepare
job applications. A real application requires a separate, one-time
confirmation and is disabled by default.

## Security modes

- **Read-only (default):** all search and read tools work; application
  submission is blocked.
- **Apply with confirmation:** set `HH_ENABLE_APPLICATIONS=true`. The client
  must first call `hh_prepare_application`, show the preview to the user, and
  call `hh_confirm_application` only after the user explicitly confirms it.

There is no one-call MCP tool for submitting an application. Confirmation is
bound to the exact vacancy, resume, and cover letter, expires after 10 minutes,
and can be used only once.

## Requirements and installation

- Python 3.10–3.13
- HeadHunter application credentials from
  [dev.hh.ru/admin](https://dev.hh.ru/admin)
- Windows Credential Manager for OAuth token storage (through `keyring`)

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements.lock
Copy-Item .env.example .env
```

`requirements.txt` contains direct dependency ranges. `requirements.lock`
contains the complete verified dependency set with hashes.

Configure `HH_CLIENT_ID`, `HH_CLIENT_SECRET`, `HH_APP_TOKEN`,
`HH_REDIRECT_URI`, and `HH_USER_AGENT` (with a real contact email) in the MCP
process environment or a secret manager. Treat `.env` as a development
template only; do not put real client secrets or OAuth tokens in it.

## OAuth authorization

```powershell
venv\Scripts\python.exe oauth_flow.py
```

The script never prints tokens. It stores the access/refresh pair as one entry
in the system credential store. Token refresh is automatic, persists rotated
refresh tokens, and retries an authenticated request at most once after a 401.

`HH_ALLOW_ENV_TOKENS=true` enables an explicit development-only process
environment fallback. It must not be used with real tokens.

## MCP configuration

Example configuration (adjust paths for your machine):

```json
{
  "mcpServers": {
    "headhunter": {
      "type": "stdio",
      "command": "D:/path/to/headhunter-mcp-server/venv/Scripts/python.exe",
      "args": ["D:/path/to/headhunter-mcp-server/server.py"],
      "env": {
        "HH_CLIENT_ID": "your_client_id",
        "HH_CLIENT_SECRET": "your_client_secret",
        "HH_APP_TOKEN": "your_app_token",
        "HH_REDIRECT_URI": "https://your-domain.example/oauth/callback",
        "HH_USER_AGENT": "HeadHunterMCP/0.1 (you@example.com)",
        "HH_ENABLE_APPLICATIONS": "false"
      }
    }
  }
}
```

## Tools

Read-only tools:

- `hh_search_vacancies`
- `hh_get_vacancy`
- `hh_get_employer`
- `hh_get_similar`
- `hh_get_areas`
- `hh_get_dictionaries`
- `hh_get_negotiations`
- `hh_get_resumes`
- `hh_get_resume` — minimized by default; excludes names and contacts
- `hh_get_resume_full` — explicit bounded view including personal/contact data

Application tools:

- `hh_prepare_application` — returns a preview and one-time token; never writes
- `hh_confirm_application` — submits only the exact stored preview

Example interaction:

1. “Prepare an application to vacancy `126209046` using resume `<resume_id>`
   and this letter: …”
2. Review the returned vacancy, employer, resume, and complete letter.
3. Explicitly say that the shown application may be submitted.
4. The client calls `hh_confirm_application` with the preview token.

If HH accepts the request, the result is `submitted`. A definite rejection is
`not_submitted`. A timeout or server-side ambiguity is `unknown`; the server
does not automatically repeat an ambiguous POST.

## Data handling

- IDs and pagination are validated before any HTTP request.
- Vacancy/company HTML is converted to bounded plain text and marked as
  untrusted external content.
- Default resume output excludes contact and identity fields.
- Tokens are excluded from MCP output and diagnostic errors.
- A vacancy description cannot create or alter an application confirmation.

## Vacancy Hunter agent

The safe agent definition is [docs/vacancy-hunter.md](docs/vacancy-hunter.md).
It has no shell or file-write tools, contains no fixed resume IDs or absolute
paths, and cannot confirm an application.

## Local verification

```powershell
venv\Scripts\python.exe -B -m unittest discover -s tests -v
venv\Scripts\ruff.exe check . --exclude venv
venv\Scripts\pip-audit.exe -r requirements.lock --disable-pip
```

CI is intentionally not configured. The focused local tests cover validation,
one-time confirmation, ambiguous application responses, token rotation and
retry limits, output sanitization, and personal-data minimization.

## Русский

Сервер по умолчанию работает только на чтение. Для откликов нужно явно задать
`HH_ENABLE_APPLICATIONS=true`, создать предпросмотр через
`hh_prepare_application`, проверить вакансию, работодателя, резюме и письмо, а
после явного согласия пользователя отдельно вызвать
`hh_confirm_application`. Токен подтверждения одноразовый и действует 10 минут.

OAuth-токены не выводятся и не сохраняются в `.env`: на Windows они хранятся в
Credential Manager через `keyring`. Обычный `hh_get_resume` не возвращает имя и
контакты; для них существует отдельный явный `hh_get_resume_full`.

Установка, конфигурация и команды проверки приведены выше. Безопасная версия
агента находится в [docs/vacancy-hunter.md](docs/vacancy-hunter.md).

## License

MIT — see [LICENSE](LICENSE).
