# Hybrid Cloudflare + Render foundation

This project now keeps its production-safe PDF processing in Render while preparing
metadata and settings persistence for a future move to Cloudflare D1 + R2.

## Current split

- Render: FastAPI app, PDF parsing, report generation.
- Local filesystem: generated/exported report files and uploaded source PDFs.
- SQLite metadata store: local development and Render-compatible stand-in for D1.

## D1-ready tables

The local SQLite database uses the same logical schema planned for D1:

- `reports`: report metadata, payload snapshots, file pointers.
- `settings_current`: current settings payload.
- `settings_audit`: admin audit trail for settings changes.
- `users`: future login/role model (`user` / `admin`).

See [d1-schema.sql](/D:/diegoluks/CONFERIR%20PONTO/docs/d1-schema.sql).

## Planned R2 mapping

- `reports/{report_id}/source.pdf`
- `reports/{report_id}/export.pdf`

The current local filesystem paths are kept in metadata so the app can transition
to R2 object keys later without changing the higher-level report model.

## Next migration steps

1. Replace local PDF/source file persistence with R2 object writes.
2. Switch recent reports and settings audit reads from local SQLite to D1.
3. Move admin and user authentication to the `users` table.
4. Add report ownership so common users only see their own history.
