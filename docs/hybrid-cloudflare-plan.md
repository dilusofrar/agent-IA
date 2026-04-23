# Hybrid Cloudflare + Render foundation

This project now keeps its production-safe PDF processing in Render while preparing
metadata and settings persistence for a future move to Cloudflare D1 + R2.

## Current split

- Render: FastAPI app, PDF parsing, report generation.
- Storage abstraction: report/source files are stored behind a local object-like storage layer.
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
- `reports/{report_id}/metadata.json`

The current local storage already uses these logical keys, so the next R2 step is
mainly a backend adapter swap instead of a route/model redesign.

## R2 runtime variables

When ready to enable Cloudflare R2 in production, configure:

- `R2_ENDPOINT_URL` (format: `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`)
- `R2_BUCKET_NAME`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_REGION` (recommended: `auto`)

If any of these are missing, the app falls back to local storage automatically.

## Next migration steps

1. Replace the local storage adapter with R2 object writes.
2. Switch recent reports and settings audit reads from local SQLite to D1.
3. Move admin and user authentication to the `users` table.
4. Add report ownership so common users only see their own history.
