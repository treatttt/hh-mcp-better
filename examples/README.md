# Examples

Run the OAuth flow from the repository root:

```powershell
venv\Scripts\python.exe oauth_flow.py
```

The script stores tokens in the system credential store and never prints or
writes them to `.env`.

Safe application flow:

1. Ask the client to prepare an application for a specific vacancy and resume.
2. Review the complete preview and cover letter.
3. Explicitly confirm the shown preview.
4. The client uses the one-time token with `hh_confirm_application`.

Application sending remains disabled until `HH_ENABLE_APPLICATIONS=true` is
set. Search and resume-reading tools work in read-only mode.
