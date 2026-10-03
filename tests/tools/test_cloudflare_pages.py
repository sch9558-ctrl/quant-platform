from __future__ import annotations

import pytest

from tools.cloudflare_pages import (
    CloudflareError,
    _app_matches,
    _assert_no_broad_policy,
    _policy_is_strict_owner_policy,
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
