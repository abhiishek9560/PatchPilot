# PatchPilot deployment

PatchPilot uses a free, split deployment while keeping account cookies
first-party:

- Vercel serves `dist/` and proxies `/api/*` through `api/proxy.mjs`;
- Render runs the FastAPI Docker service defined in `render.yaml`; and
- Neon provides PostgreSQL through the standard `DATABASE_URL` setting.

Render's own free PostgreSQL expires after 30 days, so it is intentionally not
created by the Blueprint. SQLite remains the zero-dependency local fallback.

## Deployment order

1. Create the Neon project and copy its pooled PostgreSQL connection string.
2. Deploy `render.yaml` and provide `DATABASE_URL`, `OPENAI_API_KEY`, and an
   `OPENAI_MODEL` available to that API project; leave the GitHub variables empty
   until the GitHub App exists.
3. Copy the Render `onrender.com` URL.
4. Deploy the Vercel project with `PATCHPILOT_API_URL` set to the Render URL.
5. Copy the production `vercel.app` URL and register the GitHub App.
6. Add the resulting GitHub App values to Render and redeploy.

The Render service runs a lease-based worker thread in the same free web
instance (`PATCHPILOT_WORKER_ENABLED=true`). This is appropriate for the V1
single-instance pilot and avoids a paid background-worker service.

## GitHub App settings

Create the app after both deployments have public URLs. If the frontend is
`https://patchpilot.vercel.app` and the backend is
`https://patchpilot.onrender.com`, use:

- Homepage URL: `https://patchpilot.vercel.app`
- Setup URL: `https://patchpilot.vercel.app/api/github/setup`
- Webhook URL: `https://patchpilot.onrender.com/api/github/webhooks`
- Webhook secret: a new high-entropy random value, also stored as
  `GITHUB_WEBHOOK_SECRET` on Render
- Request user authorization during installation: disabled

Repository permissions:

- Contents: Read and write
- Issues: Read-only
- Metadata: Read-only
- Pull requests: Read and write

Subscribe to the `Issues` event. Installation and repository-selection events
are delivered for GitHub App lifecycle changes.

After creating the app:

1. On GitHub, open **Settings → Developer settings → GitHub Apps**, then open
   the new PatchPilot app.
2. Copy the numeric **App ID** from the app's General page into Render as
   `GITHUB_APP_ID`. This is not the OAuth Client ID.
3. Copy the slug from `https://github.com/apps/<slug>` into Render as
   `GITHUB_APP_SLUG`.
4. Under **Private keys**, select **Generate a private key**. Open the downloaded
   `.pem` file and paste its complete contents into Render as
   `GITHUB_PRIVATE_KEY`.
5. Generate your own random webhook secret, enter the same value in GitHub's
   **Webhook secret** field and Render's `GITHUB_WEBHOOK_SECRET` variable.
6. Redeploy Render, register or sign in to PatchPilot, and select
   **Connect GitHub**.

The current installation flow does not use GitHub OAuth user authorization, so
the OAuth Client ID and Client secret are not production variables.

Never commit the private key, webhook secret, `.env`, database, or workspace
content.

## Local Docker

Copy `.env.example` to `.env`, fill the required GitHub values, and run:

```bash
docker compose up --build -d
```

To exercise PostgreSQL locally instead of SQLite:

```bash
DATABASE_URL=postgresql://patchpilot:patchpilot-dev-only@postgres:5432/patchpilot \
  docker compose --profile postgres up --build
```

GitHub does not deliver webhooks to localhost. A public deployment or a secure
development webhook forwarder is required for the complete installation flow.
