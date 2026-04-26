# Cloudflare Containers migration

This repository is now prepared for a full migration from Render to Cloudflare Containers.

## Target architecture

- Cloudflare Worker: edge entrypoint, routing, TLS, observability.
- Cloudflare Container: runs the existing FastAPI + PDF processing app.
- Cloudflare D1: primary database for users, reports, settings and audits.
- Cloudflare R2: primary object storage for PDFs and generated exports.
- Local SQLite inside the app: warm cache/fallback hydrated from D1 at startup.

## Why this structure

Cloudflare documents that Containers are controlled from a Worker, using a Durable Object
binding plus the `Container` class, and that Wrangler can build and push a Dockerfile
directly during `wrangler deploy`.

Sources:
- [Containers overview](https://developers.cloudflare.com/containers/)
- [Containers getting started](https://developers.cloudflare.com/containers/get-started/)
- [Wrangler containers configuration](https://developers.cloudflare.com/workers/wrangler/configuration/)
- [Container interface](https://developers.cloudflare.com/containers/container-class/)

## Files added for the migration

- `cloudflare/wrangler.jsonc`
- `cloudflare/src/index.ts`
- `cloudflare/package.json`
- `cloudflare/tsconfig.json`

These files do not replace Render yet. They add the Cloudflare deployment path in parallel.

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
wrangler secret put D1_ACCOUNT_ID
wrangler secret put D1_DATABASE_ID
wrangler secret put D1_API_TOKEN
wrangler secret put R2_ENDPOINT_URL
wrangler secret put R2_BUCKET_NAME
wrangler secret put R2_ACCESS_KEY_ID
wrangler secret put R2_SECRET_ACCESS_KEY
```

Optional:

```bash
wrangler secret put ADMIN_USERNAME
wrangler secret put D1_API_BASE_URL
```

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

- This Worker currently proxies everything to the FastAPI app inside the container.
- D1 and R2 remain the system of record.
- The app already supports D1 as the primary persistence path and R2 as storage.
- After the billing issue is resolved, this path should let you cut over from Render without
  redesigning the core Python logic first.

## Next refactors after first successful Cloudflare deploy

1. Move `healthz` and lightweight diagnostics into the Worker layer too.
2. Replace D1 REST credentials with first-class Worker bindings where it adds value.
3. Split static assets from the container if you want cheaper edge delivery.
4. Add staging and production environments in `wrangler.jsonc`.
