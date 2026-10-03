from __future__ import annotations

import pytest

from tools.cloudflare_pages import (
    AccessPermissionError,
    CloudflareError,
    _app_matches,
    _assert_no_broad_policy,
    _policy_is_strict_owner_policy,
    ensure_project,
)


ACCOUNT = "301c3fbffec59a5d5827040ff30eb62f"


def test_access_app_matches_domain_or_public_destination():
    assert _app_matches({"domain": "quant-platform.pages.dev"}, "quant-platform.pages.dev")
    assert _app_matches(
        {"destinations": [{"type": "public", "uri": "quant-platform.pages.dev"}]},
        "quant-platform.pages.dev",
    )
    assert not _app_matches({"domain": "other.pages.dev"}, "quant-platform.pages.dev")


def test_account_member_policy_is_strict():
    policy = {
        "decision": "allow",
        "include": [{"cloudflare_account_member": {"account_id": ACCOUNT}}],
    }
    assert _policy_is_strict_owner_policy(policy, ACCOUNT)


@pytest.mark.parametrize(
    "policy",
    [
        {"decision": "bypass", "include": [{"everyone": {}}]},
        {"decision": "allow", "include": [{"everyone": {}}]},
        {"decision": "allow", "include": [{"email_domain": {"domain": "gmail.com"}}]},
    ],
)
def test_broad_or_bypass_policy_fails_closed(policy):
    with pytest.raises(CloudflareError):
        _assert_no_broad_policy([policy], ACCOUNT)


def test_only_account_member_allow_policy_is_accepted():
    policy = {
        "name": "owner",
        "decision": "allow",
        "include": [{"cloudflare_account_member": {"account_id": ACCOUNT}}],
    }
    _assert_no_broad_policy([policy], ACCOUNT)


def test_project_create_race_is_accepted_only_when_project_can_be_re_read():
    class RacingClient:
        account_id = ACCOUNT
        def __init__(self):
            self.gets = 0
        def request(self, method, path, *, payload=None, allow_404=False):
            if method == "GET":
                self.gets += 1
                return None if self.gets == 1 else {"name": "quant-platform"}
            raise CloudflareError("already exists", status=409)

    assert ensure_project(RacingClient(), "quant-platform")["name"] == "quant-platform"


def test_project_create_error_stays_fatal_when_project_still_missing():
    class FailingClient:
        account_id = ACCOUNT
        def request(self, method, path, *, payload=None, allow_404=False):
            if method == "GET":
                return None
            raise CloudflareError("forbidden", status=403)

    with pytest.raises(CloudflareError, match="forbidden"):
        ensure_project(FailingClient(), "quant-platform")


def test_access_permission_error_is_distinct():
    err = AccessPermissionError("missing", status=403)
    assert isinstance(err, CloudflareError)
    assert err.status == 403
