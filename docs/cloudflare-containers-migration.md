# Cloudflare Containers migration

This repository is now prepared for a full migration from Render to Cloudflare Containers.

## Target architecture

- Cloudflare Worker: edge entrypoint, routing, TLS, observability.
- Cloudflare Container: runs the existing FastAPI + PDF processing app.
- Cloudflare D1: primary database for users, reports, settings and audits.
- Cloudflare R2: primary object storage for PDFs and generated exports.
- In-memory fallback only for emergency runtime scenarios when D1 is unavailable.

## Why this structure

Cloudflare documents that Containers are controlled from a Worker, using a Durable Object
binding plus the `Container` class, and that Wrangler can build and push a Dockerfile
directly during `wrangler deploy`.

Sources:
- [Containers overview](https://developers.cloudflare.com/containers/)
- [Containers getting started](https://developers.cloudflare.com/containers/get-started/)
- [Wrangler containers configuration](https://developers.cloudflare.com/workers/wrangler/configuration/)
- [Container interface](https://developers.cloudflare.com/containers/container-class/)
- [Connect to Workers and Bindings](https://developers.cloudflare.com/containers/platform-details/workers-connections/)

## Files added for the migration

- `cloudflare/wrangler.jsonc`
- `cloudflare/src/index.ts`
- `cloudflare/package.json`
- `cloudflare/tsconfig.json`

These files now define the Cloudflare deployment path. Render should remain only as a
temporary rollback target until the first production cutover is validated.

Important:
- native D1 and R2 access from inside the container uses outbound handlers, which require
  `@cloudflare/containers` version `0.2.0` or later according to Cloudflare's March 26,
  2026 Containers changelog.

Important:
- if the Cloudflare connected-build project was originally created with a different Worker
  name (for example `project1`), keep `wrangler.jsonc` aligned to that connected-build
  name until the first container application is fully created.
- after the first successful rollout, rename/recreate the Cloudflare project in a controlled
  step if you want the public Worker name to match `agent-ia-ponto`.

## How the new Worker works

- A single Durable Object-backed container instance is named `primary`.
- The Worker starts the container if needed, waits for port `8000`, and proxies the request.
- Runtime environment variables are passed into the container on startup.

This keeps the existing Python app mostly unchanged while moving infrastructure to Cloudflare.

## Required Cloudflare secrets

Before deploying the Worker, add these secrets with Wrangler:

```bash
wrangler secret put ADMIN_PASSWORD
wrangler secret put ADMIN_SESSION_SECRET
wrangler secret put APP_SESSION_SECRET
```

Optional:

```bash
wrangler secret put ADMIN_USERNAME
```

When using first-class Cloudflare bindings from Containers, the Worker only needs two
runtime variables to discover the existing bindings:

```bash
wrangler secret put D1_BINDING_NAME
wrangler secret put R2_BINDING_NAME
```

Set them to the binding names already attached to the Worker in the Cloudflare dashboard.
The Worker will expose those bindings to the Python container through outbound handlers,
so the container no longer needs D1 API tokens or R2 S3-compatible credentials.

For dashboard-based deployments, split configuration in two places:

- Build-time variables
  - `CLOUDFLARE_API_TOKEN`
  - `CLOUDFLARE_ACCOUNT_ID`
- Runtime variables and secrets for the Worker/container
  - `ADMIN_USERNAME`
  - `ADMIN_PASSWORD`
  - `ADMIN_SESSION_SECRET`
  - `APP_SESSION_SECRET`
  - `D1_BINDING_NAME`
  - `R2_BINDING_NAME`
  - `R2_BUCKET_NAME` (optional, for diagnostics/location display)
  - `R2_REGION`

## First deployment steps

From `cloudflare/`:

```bash
npm install
npx wrangler deploy
```

Cloudflare documents that the first container deployment can take a few minutes because:
- Wrangler builds the Docker image
- pushes it to the Cloudflare registry
- provisions the container runtime

Source:
- [Getting started](https://developers.cloudflare.com/containers/get-started/)

## Important notes

- This Worker proxies everything to the FastAPI app inside the container.
- D1 and R2 remain the system of record.
- The app already supports D1 as the primary persistence path and R2 as storage.
- This path lets you cut over from Render without redesigning the core Python logic first.

## Production cutover checklist

1. Deploy the Worker and container successfully.
2. Confirm all Worker runtime variables and secrets are present.
3. Validate the default `workers.dev` hostname:
   - `/healthz`
   - app login
   - admin login
   - PDF processing
   - D1-backed users and settings
   - R2-backed report persistence and exports
4. Point `ubuntucode.com` at the Cloudflare Worker route.
5. Keep Render online briefly only for rollback.
6. After stable validation, disable or delete the Render service.

## Next refactors after first successful Cloudflare deploy

1. Move `healthz` and lightweight diagnostics into the Worker layer too.
2. Remove legacy D1 and R2 credential variables after the native binding path is validated.
3. Split static assets from the container if you want cheaper edge delivery.
4. Add staging and production environments in `wrangler.jsonc`.
