# Hybrid Cloudflare + Render foundation

This project now keeps its production-safe PDF processing in Render while preparing
metadata and settings persistence for a future move to Cloudflare D1 + R2.

## Current split

- Render: FastAPI app, PDF parsing, report generation.
- Storage abstraction: report/source files are stored behind a local object-like storage layer.
- SQLite metadata store: local development and Render-compatible stand-in for D1.
- Optional D1 mirror: when configured, the app mirrors metadata, users and settings audit to Cloudflare D1 over the REST API.

## D1-ready tables

The local SQLite database uses the same logical schema planned for D1:

- `reports`: report metadata, payload snapshots, file pointers and owner attribution.
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

1. Create the D1 database in Cloudflare with a name such as `agent-ia-ponto`.
2. Set `D1_ACCOUNT_ID`, `D1_DATABASE_ID` and `D1_API_TOKEN` in Render.
3. Let the app bootstrap the schema automatically from `docs/d1-schema.sql`.
4. Observe `healthz` until `persistenceBackend` changes from `sqlite` to `sqlite+d1`.
5. After validation, move session/login ownership fully into D1 and filter report history by owner.

## D1 runtime variables

- `D1_ACCOUNT_ID`
- `D1_DATABASE_ID`
- `D1_API_TOKEN`
- optional: `D1_API_BASE_URL` (defaults to `https://api.cloudflare.com/client/v4`)

The D1 API token needs at least `D1 Read` and `D1 Write` permissions on the target account, as described in the Cloudflare REST API docs:
- [Create D1 Database](https://developers.cloudflare.com/api/resources/d1/subresources/database/methods/get/)
- [Query D1 Database](https://developers.cloudflare.com/api/resources/d1/subresources/database/methods/query/)
