"""OIDC authentication against Authentik (Authorization Code flow).

The app owns its own session: a successful OIDC login stores the user's
identity in the signed session cookie. The authenticated interface is gated
both by Authentik (the application is bound to the ``dropbox`` group) and, as
an in-app backstop, by checking the ``groups`` claim here.
"""
from __future__ import annotations

import logging

from authlib.integrations.starlette_client import OAuth
from fastapi import Request

from .config import settings

log = logging.getLogger("beckham_share.auth")

oauth = OAuth()
if settings.oidc_configured:
    oauth.register(
        name="authentik",
        server_metadata_url=settings.oidc_discovery_url,
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        client_kwargs={"scope": settings.oidc_scopes},
    )


class CurrentUser:
    """A logged-in user, reconstructed from the session."""

    def __init__(self, data: dict):
        self.sub: str = data.get("sub", "")
        self.email: str = data.get("email", "")
        self.name: str = data.get("name") or data.get("preferred_username") or self.email
        self.groups: list[str] = data.get("groups", []) or []

    @property
    def in_required_group(self) -> bool:
        if self.groups:
            return settings.required_group in self.groups
        # No groups claim at all. Authentik is configured to send one, so its
        # absence means the provider's scope mapping has drifted, not that this
        # user happens to belong to nothing. Authentik's own binding on the
        # application should still have kept non-members out, but that is the
        # layer we don't control — and this check exists precisely to not depend
        # on it. So the answer is no, unless an operator has deliberately said
        # otherwise while repairing the mapping.
        if settings.allow_missing_groups_claim:
            log.warning(
                "OIDC token carried no groups claim for %s; admitting anyway because "
                "ALLOW_MISSING_GROUPS_CLAIM is set. Fix the provider's groups scope mapping.",
                self.sub,
            )
            return True
        log.warning(
            "OIDC token carried no groups claim for %s; refusing. The provider's groups "
            "scope mapping is missing or not bound to this application.",
            self.sub,
        )
        return False


def get_current_user(request: Request) -> CurrentUser | None:
    data = request.session.get("user")
    return CurrentUser(data) if data else None


def store_user(request: Request, userinfo: dict) -> None:
    request.session["user"] = {
        "sub": userinfo.get("sub"),
        "email": userinfo.get("email"),
        "name": userinfo.get("name") or userinfo.get("preferred_username"),
        "groups": userinfo.get("groups", []),
    }


def clear_user(request: Request) -> None:
    request.session.pop("user", None)
