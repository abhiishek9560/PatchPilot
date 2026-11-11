# PatchPilot deployment

PatchPilot's FastAPI process serves both the browser dashboard and the API. A
single public service therefore keeps account cookies, GitHub redirects, and API
requests on the same origin.

## Render V1

The repository root contains `render.yaml`. It creates:

- one Docker web service;
- an HTTP health check at `/health`;
- one persistent disk mounted at `/data`;
- a production SQLite database at `/data/patchpilot.db`; and
- a persistent agent workspace at `/data/workspaces`.

The persistent disk requires Render's paid 0.5 CPU / 512 MB service and limits
this V1 to one instance. PostgreSQL and a separate sandbox worker are the next
production architecture step.

During the first Blueprint deployment, provide the GitHub App variables. The
OpenAI variables can remain empty while the deterministic planner is enabled.

## GitHub App settings

Create the app only after Render has assigned the public service URL. If the
service URL is `https://patchpilot.onrender.com`, use:

- Homepage URL: `https://patchpilot.onrender.com`
- Setup URL: `https://patchpilot.onrender.com/api/github/setup`
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

1. Generate and download a private key.
2. Store the numeric App ID as `GITHUB_APP_ID`.
3. Store the app's URL slug as `GITHUB_APP_SLUG`.
4. Store the complete PEM as `GITHUB_PRIVATE_KEY`.
5. Deploy the new environment values.
6. Register or sign in to PatchPilot and select **Connect GitHub**.

Never commit the private key, webhook secret, `.env`, database, or workspace
content.

## Local Docker

Copy `.env.example` to `.env`, fill the required GitHub values, and run:

```bash
docker compose up --build -d
```

GitHub does not deliver webhooks to localhost. A public deployment or a secure
development webhook forwarder is required for the complete installation flow.
