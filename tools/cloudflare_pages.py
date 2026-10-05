#!/usr/bin/env python3
"""Idempotent Cloudflare Pages + Access bootstrap/check for the private dashboard.

Security invariant: never deploy research data to an unprotected Pages project.
Bootstrap first proves the token can manage Access, then creates an empty Pages
project (if needed), installs a Cloudflare-account-member Access policy, and
only then allows the separate Wrangler deploy step to upload site/.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Any

import requests

API = "https://api.cloudflare.com/client/v4"
DEFAULT_PROJECT = "quant-platform"
DEFAULT_HOSTNAME = "quant-platform.pages.dev"
POLICY_NAME = "Quant platform account members only"
APP_NAME = "Quant Platform Dashboard"


class CloudflareError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class AccessPermissionError(CloudflareError):
    """The configured token cannot inspect/manage Cloudflare Access."""


@dataclass
class Client:
    account_id: str
    token: str
    timeout: int = 30

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        allow_404: bool = False,
    ) -> Any:
        response = requests.request(
            method,
            f"{API}{path}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        if allow_404 and response.status_code == 404:
            return None
        try:
            body = response.json()
        except Exception:
            body = {"success": False, "errors": [{"message": response.text[:500]}]}
        if response.status_code >= 400 or not body.get("success", False):
            errors = body.get("errors") or []
            detail = "; ".join(str(e.get("message", e)) for e in errors) or response.text[:500]
            raise CloudflareError(
                f"Cloudflare API {method} {path} failed ({response.status_code}): {detail}",
                status=response.status_code,
            )
        return body.get("result")

    def apps(self) -> list[dict[str, Any]]:
        result = self.request("GET", f"/accounts/{self.account_id}/access/apps?per_page=100")
        return list(result or [])

    def idps(self) -> list[dict[str, Any]]:
        result = self.request(
            "GET",
            f"/accounts/{self.account_id}/access/identity_providers?per_page=1000",
        )
        return list(result or [])


def _app_matches(app: dict[str, Any], hostname: str) -> bool:
    if str(app.get("domain", "")).rstrip("/") == hostname:
        return True
    for dest in app.get("destinations") or []:
        if str(dest.get("uri", "")).rstrip("/") == hostname:
            return True
    return False


def _is_account_member_rule(rule: dict[str, Any], account_id: str) -> bool:
    member = rule.get("cloudflare_account_member")
    if not isinstance(member, dict):
        return False
    configured = member.get("account_id")
    return configured in (None, "", account_id)


def _policy_is_strict_owner_policy(policy: dict[str, Any], account_id: str) -> bool:
    if policy.get("decision") != "allow":
        return False
    includes = policy.get("include") or []
    return bool(includes) and all(_is_account_member_rule(r, account_id) for r in includes)


def _assert_no_broad_policy(policies: list[dict[str, Any]], account_id: str) -> None:
    for policy in policies:
        decision = policy.get("decision")
        if decision == "bypass":
            raise CloudflareError(
                f"Access policy {policy.get('name')!r} bypasses authentication; refusing to deploy."
            )
        if decision == "allow" and not _policy_is_strict_owner_policy(policy, account_id):
            raise CloudflareError(
                f"Access policy {policy.get('name')!r} broadens access beyond Cloudflare "
                "account members; refusing to deploy."
            )


def probe_access_permissions(client: Client) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fail before creating a Pages project if the token cannot inspect Access."""
    try:
        apps = client.apps()
        idps = client.idps()
    except CloudflareError as exc:
        if exc.status in (401, 403):
            raise AccessPermissionError(
                "Cloudflare Access management is not authorized by the configured token. "
                "Create or update CLOUDFLARE_ACCESS_API_TOKEN for this account with "
                "Access: Apps and Policies Edit and Access: Identity Providers Edit. "
                "Store it in GitHub repository Settings -> Secrets and variables -> Actions. "
                "No Pages project was created and no public fallback was attempted."
            ) from exc
        raise
    return apps, idps


def ensure_cloudflare_idp(client: Client, idps: list[dict[str, Any]]) -> dict[str, Any]:
    existing = next((x for x in idps if x.get("type") == "cloudflare"), None)
    if existing:
        return existing
    return client.request(
        "POST",
        f"/accounts/{client.account_id}/access/identity_providers",
        payload={
            "name": "Cloudflare",
            "type": "cloudflare",
            "config": {"restrict_to_account_members": True},
        },
    )


def ensure_project(client: Client, project: str) -> dict[str, Any]:
    """Create the Pages project idempotently, including concurrent-create races.

    Permission/authentication failures remain fatal. A create error is ignored
    only when a follow-up GET proves that the requested project now exists.
    """
    path = f"/accounts/{client.account_id}/pages/projects/{project}"
    existing = client.request("GET", path, allow_404=True)
    if existing:
        return existing
    try:
        return client.request(
            "POST",
            f"/accounts/{client.account_id}/pages/projects",
            payload={"name": project, "production_branch": "master"},
        )
    except CloudflareError:
        existing = client.request("GET", path, allow_404=True)
        if existing:
            return existing
        raise


def find_app(apps: list[dict[str, Any]], hostname: str) -> dict[str, Any] | None:
    return next((app for app in apps if _app_matches(app, hostname)), None)


def ensure_access_app(
    client: Client,
    apps: list[dict[str, Any]],
    idp: dict[str, Any],
    hostname: str,
) -> dict[str, Any]:
    existing = find_app(apps, hostname)
    if existing:
        return existing
    payload: dict[str, Any] = {
        "name": APP_NAME,
        "type": "self_hosted",
        "domain": hostname,
        "session_duration": "24h",
    }
    if idp.get("id"):
        payload["allowed_idps"] = [idp["id"]]
    return client.request(
        "POST",
        f"/accounts/{client.account_id}/access/apps",
        payload=payload,
    )


def policies(client: Client, app_id: str) -> list[dict[str, Any]]:
    result = client.request(
        "GET",
        f"/accounts/{client.account_id}/access/apps/{app_id}/policies?per_page=100",
    )
    return list(result or [])


def ensure_owner_policy(client: Client, app: dict[str, Any]) -> dict[str, Any]:
    current = policies(client, app["id"])
    _assert_no_broad_policy(current, client.account_id)
    strict = next(
        (p for p in current if _policy_is_strict_owner_policy(p, client.account_id)),
        None,
    )
    if strict:
        return strict
    return client.request(
        "POST",
        f"/accounts/{client.account_id}/access/apps/{app['id']}/policies",
        payload={
            "name": POLICY_NAME,
            "decision": "allow",
            "precedence": 1,
            "include": [
                {"cloudflare_account_member": {"account_id": client.account_id}}
            ],
        },
    )


def check_ready(
    pages_client: Client,
    access_client: Client,
    project: str,
    hostname: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    project_obj = pages_client.request(
        "GET",
        f"/accounts/{pages_client.account_id}/pages/projects/{project}",
        allow_404=True,
    )
    if not project_obj:
        raise CloudflareError(f"Cloudflare Pages project {project!r} does not exist.")
    apps = access_client.apps()
    app = find_app(apps, hostname)
    if not app:
        raise CloudflareError(f"No Cloudflare Access application protects {hostname}.")
    current = policies(access_client, app["id"])
    _assert_no_broad_policy(current, access_client.account_id)
    if not any(
        _policy_is_strict_owner_policy(p, access_client.account_id)
        for p in current
    ):
        raise CloudflareError(
            f"{hostname} has no strict Cloudflare-account-member allow policy."
        )
    return project_obj, app


def bootstrap(
    pages_client: Client,
    access_client: Client,
    project: str,
    hostname: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    # Access capability is proved before Pages creation, so a Pages-only token
    # can never accidentally create an unauthenticated public dashboard.
    apps, idps = probe_access_permissions(access_client)
    idp = ensure_cloudflare_idp(access_client, idps)
    ensure_project(pages_client, project)
    apps = access_client.apps()
    app = ensure_access_app(access_client, apps, idp, hostname)
    ensure_owner_policy(access_client, app)
    return check_ready(pages_client, access_client, project, hostname)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preflight", "bootstrap", "check"))
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--hostname", default=DEFAULT_HOSTNAME)
    args = parser.parse_args()

    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    pages_token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    access_token = os.getenv("CLOUDFLARE_ACCESS_API_TOKEN", "").strip() or pages_token
    if not account_id or not pages_token:
        missing = []
        if not account_id:
            missing.append(
                "CLOUDFLARE_ACCOUNT_ID (Cloudflare Dashboard -> Workers & Pages -> Account Details)"
            )
        if not pages_token:
            missing.append(
                "CLOUDFLARE_API_TOKEN (Custom API token with Account -> Cloudflare Pages -> Edit)"
            )
        print(
            "Missing Cloudflare configuration: " + "; ".join(missing)
            + ". Store the value(s) in GitHub repository Settings -> Secrets and variables -> Actions. "
              "Token values must never be printed.",
            file=sys.stderr,
        )
        return 2

    pages_client = Client(account_id=account_id, token=pages_token)
    access_client = Client(account_id=account_id, token=access_token)
    try:
        if args.mode == "preflight":
            probe_access_permissions(access_client)
            print("Cloudflare Access capability ready.")
            return 0
        if args.mode == "bootstrap":
            project, app = bootstrap(
                pages_client, access_client, args.project, args.hostname
            )
        else:
            project, app = check_ready(
                pages_client, access_client, args.project, args.hostname
            )
    except AccessPermissionError as exc:
        print(f"ACCESS_PERMISSION_MISSING: {exc}", file=sys.stderr)
        return 3
    except CloudflareError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        f"Cloudflare private dashboard ready: project={project.get('name', args.project)} "
        f"hostname={args.hostname} access_app={app.get('id', 'unknown')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
