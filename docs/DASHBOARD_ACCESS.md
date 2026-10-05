# Private dashboard access checklist

This page lists only the user actions required to view the private dashboard.
Never commit or paste secret values into issues, logs, documentation, or chat.

## 1. Cloudflare Pages token

1. Open Cloudflare Dashboard -> My Profile -> API Tokens.
2. Create a Custom API token restricted to the account that will own this project.
3. Grant **Account -> Cloudflare Pages -> Edit** (Cloudflare API permission name: Pages Write).
4. In GitHub, open this repository -> Settings -> Secrets and variables -> Actions.
5. Create the secret **CLOUDFLARE_API_TOKEN**.

This token is used only for Pages project management/deployment.

## 2. Cloudflare Access token

The dashboard is never published unless Access can be inspected and configured first.

1. Create a separate Cloudflare Custom API token for the same account.
2. Grant:
   - **Account -> Access: Apps and Policies -> Edit**
   - **Account -> Access: Identity Providers -> Edit**
3. Save it in GitHub Actions secrets as **CLOUDFLARE_ACCESS_API_TOKEN**.

Using a separate Access token is preferable to broadening the Pages token.

## 3. Cloudflare Account ID

1. Open Cloudflare Dashboard -> Workers & Pages -> Account Details, or use the dashboard search for **Copy account ID**.
2. Save the Account ID in GitHub Actions secrets as **CLOUDFLARE_ACCOUNT_ID**.

The value itself must not be committed to documentation.

## 4. Optional project name

The workflow defaults to the project name **quant-platform**.
Only if a different private Pages project name is required, add
**CLOUDFLARE_PROJECT_NAME** as a GitHub Actions secret.

## 5. Private dashboard artifact key

The workflow currently encrypts research/dashboard artifacts using AES-256-CBC
with PBKDF2 (200,000 iterations).

For security, use an independent high-entropy secret named
**DASHBOARD_ARTIFACT_KEY** in GitHub Actions. Do not reuse a Cloudflare API token
as an encryption key.

The current workflow still supports a legacy Cloudflare-token fallback for
compatibility. Removing that fallback and making this secret mandatory is a
separate security change and is not enabled without explicit approval.

## 6. How to confirm success

Run **Daily Research Pipeline & Private Dashboard** from GitHub Actions.

Success means all of the following:

- **Dashboard Build** completes and `tools/verify_dashboard_build.py` passes.
- **Cloudflare private deployment preflight** exits successfully.
- **Bootstrap private Pages + Access** and **Publish to Cloudflare Pages** run rather than being skipped.
- **Verify root is authentication-protected** receives a redirect/authentication
  response (301/302/303/307/308/401/403), never anonymous HTTP 200.
- An anonymous request to the Pages hostname cannot read the dashboard.

If Access permission is missing, the workflow must continue to say:
**No public fallback was attempted.**

## Temporary private access while Cloudflare is not ready — analysis only

The workflow already uploads `encrypted-dashboard-site-<run_id>` as a GitHub
Actions artifact with a **1-day retention period**. The artifact is encrypted
before upload.

Security properties:

- GitHub repository/Actions authorization controls who can download the artifact.
- The payload remains encrypted at rest as an artifact.
- Decryption requires `DASHBOARD_ARTIFACT_KEY`.
- No public URL or public Pages fallback is created.

Risks:

- Anyone with both repository artifact access and the decryption key can read the dashboard.
- Reusing the Cloudflare API token as the encryption key couples two secrets and increases blast radius.
- A one-day artifact lifetime is operationally inconvenient but minimizes retained exposure.
- The decryption key must be transferred to the user's local environment without
  putting it into shell history, logs, documentation, or chat.

No new artifact distribution or deployment path is enabled by this document.
Activation or workflow changes require explicit user approval first.
