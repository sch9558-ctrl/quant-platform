# User actions blocking full validation

This is the single checklist for external values that the repository cannot create or guess.
**Never paste the secret values into commits, issues, workflow logs, documentation, or chat.**

The order below is by immediate operational effect.

| Priority | GitHub Actions secret(s) | Where to obtain it | Required permission / entitlement | What becomes green after it is correct |
|---|---|---|---|---|
| **1** | `CLOUDFLARE_ACCOUNT_ID` | Cloudflare Dashboard: https://dash.cloudflare.com/ — copy the Account ID from **Workers & Pages -> Account Details** or use **Copy account ID**. Reference: https://developers.cloudflare.com/fundamentals/account/find-account-and-zone-ids/ | No API-token scope belongs to the ID itself. You must be able to view the target Cloudflare account. The existing Pages/Access tokens are checked separately by the workflow. | The deploy job can get past **Require Cloudflare Pages credentials** and execute Access preflight. If preflight and bootstrap also pass, the encrypted, verified dashboard can be published behind Cloudflare Access. |
| **2** | `DATA_GO_KR_SERVICE_KEY` | Public Data Portal: https://www.data.go.kr/ — search for **금융위원회_주식시세정보** and complete its OpenAPI 활용신청. | Approval/use entitlement for that OpenAPI. Register the **complete decoded service key** expected by the repository contract (currently 88 characters after URL decoding; do not truncate it). | `test_live_data_go_kr_daily_snapshot_contract` can proceed instead of failing key-format validation. This restores the only currently usable first-party Korean stock-price path; KRX HTTP 403 remains a separate external block. |
| **3** | `KIS_APP_KEY` + `KIS_APP_SECRET` | Korea Investment & Securities Open API: https://apiportal.koreainvestment.com/about-howto | Apply for KIS Open API service and obtain APP Key / APP Secret. Only read/query capability used by this research path is needed; **live trading remains permanently disabled**. | `test_live_kis_credit_ratio_contract` can exercise Korean credit-balance/event risk inputs instead of failing as unconfigured. |
| **4** | `STOOQ_API_KEY` | Stooq CSV key page used by the provider contract: https://stooq.com/q/d/?s=aapl.us&get_apikey | No repository-side write/trading permission. Obtain the CSV download API key accepted by Stooq and keep it secret. | `test_live_stooq_us_secondary_contract` can run the independent US secondary-source cross-check instead of failing because the key is absent. |

## Where to register the values

Repository: **Settings -> Secrets and variables -> Actions -> Repository secrets**

Direct repository settings page:

https://github.com/sch9558-ctrl/quant-platform/settings/secrets/actions

Do not put any of these values in `.env.example`, source files, documentation, test fixtures, or workflow YAML.

## Current verified state

The latest completed pre-round-6 dashboard deploy attempt showed:

- `CLOUDFLARE_ACCOUNT_ID`: empty.
- effective `CLOUDFLARE_API_TOKEN`: non-empty (GitHub masked it as `***`).
- effective `CLOUDFLARE_ACCESS_API_TOKEN`: non-empty, **but the mask cannot prove it is a separately registered Access token** because the workflow falls back to the Pages token.
- effective `DASHBOARD_ARTIFACT_KEY`: non-empty, **but the mask cannot prove it is a separately registered artifact key** because the workflow also has a legacy token fallback.

Therefore the next confirmed user action is to add `CLOUDFLARE_ACCOUNT_ID`. The subsequent run must still prove Access preflight and bootstrap permissions before the Cloudflare setup can be called complete.
