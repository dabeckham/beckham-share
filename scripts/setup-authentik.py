"""Configure Authentik for Beckham Share — idempotent, additive.

Run on the host against the live Authentik (project `idp`):

    docker compose -p idp exec -T authentik-server ak shell < scripts/setup-authentik.py

Creates/ensures:
  * group `dropbox` and members dabeckham + hlbeckham
  * an OAuth2/OIDC provider + application (slug `beckham-share`)
  * a `groups` scope mapping (so the OIDC token carries group membership)
  * a policy binding restricting the application to the `dropbox` group

Prints OIDC_CLIENT_ID / OIDC_CLIENT_SECRET on success for wiring into .env.
"""
import traceback

SLUG = "beckham-share"
APP_NAME = "Beckham Share"
# share.beckham.ai is canonical; the others are accepted so a login begun on any
# host still completes (the app canonicalizes, but this is belt-and-suspenders).
REDIRECTS = [
    "https://share.beckham.ai/auth/callback",
    "https://dropbox.beckham.ai/auth/callback",
    "https://buckets.beckham.ai/auth/callback",
]
GROUP = "dropbox"
MEMBERS = ["dabeckham", "hlbeckham"]

try:
    from authentik.core.models import Application, Group, User
    from authentik.crypto.models import CertificateKeyPair
    from authentik.flows.models import Flow, FlowDesignation
    from authentik.policies.models import PolicyBinding
    from authentik.providers.oauth2.models import (
        ClientType,
        GrantTypes,
        OAuth2Provider,
        RedirectURI,
        RedirectURIMatchingMode,
        ScopeMapping,
    )

    # ── group + members ────────────────────────────────────────────────
    group, _ = Group.objects.get_or_create(name=GROUP)
    for username in MEMBERS:
        user = User.objects.filter(username=username).first()
        if not user:
            user = User.objects.create(username=username, name=username, is_active=True)
            user.set_unusable_password()
            user.save()
            print(f"created user {username} (set a password / send enrollment in the UI)")
        user.ak_groups.add(group)
    print(f"group '{GROUP}' members: {[u.username for u in group.users.all()]}")

    # ── flows + signing key ────────────────────────────────────────────
    auth_flow = (
        Flow.objects.filter(slug="default-provider-authorization-implicit-consent").first()
        or Flow.objects.filter(designation=FlowDesignation.AUTHORIZATION).first()
    )
    inval_flow = (
        Flow.objects.filter(slug="default-provider-invalidation-flow").first()
        or Flow.objects.filter(designation=FlowDesignation.INVALIDATION).first()
    )
    signing_key = (
        CertificateKeyPair.objects.filter(name__icontains="authentik Self-signed").first()
        or CertificateKeyPair.objects.first()
    )

    # ── scope mappings: standard OIDC + a groups claim ─────────────────
    scopes = list(ScopeMapping.objects.filter(scope_name__in=["openid", "email", "profile"]))
    groups_map, _ = ScopeMapping.objects.get_or_create(
        scope_name="groups",
        defaults=dict(
            name="Beckham Share - OIDC groups",
            expression='return {"groups": [group.name for group in request.user.ak_groups.all()]}',
        ),
    )
    scopes.append(groups_map)

    # ── provider ───────────────────────────────────────────────────────
    provider = OAuth2Provider.objects.filter(name=SLUG).first()
    if not provider:
        provider = OAuth2Provider.objects.create(
            name=SLUG,
            client_type=ClientType.CONFIDENTIAL,
            authorization_flow=auth_flow,
            invalidation_flow=inval_flow,
            signing_key=signing_key,
        )
    else:
        provider.authorization_flow = auth_flow
        provider.invalidation_flow = inval_flow
        provider.signing_key = signing_key

    # Created via the ORM, grant_types defaults to empty, which makes Authentik
    # reject the authorization-code flow ("invalid_request"). Set it explicitly.
    provider.grant_types = [GrantTypes.AUTHORIZATION_CODE, GrantTypes.REFRESH_TOKEN]

    # redirect_uris is a property backed by structured RedirectURI entries.
    def _ru(url):
        try:
            return RedirectURI(RedirectURIMatchingMode.STRICT, url)
        except TypeError:
            from authentik.providers.oauth2.models import RedirectURIType
            rtype = getattr(RedirectURIType, "URL", None) or list(RedirectURIType)[0]
            return RedirectURI(RedirectURIMatchingMode.STRICT, url, rtype)

    provider.redirect_uris = [_ru(u) for u in REDIRECTS]
    provider.save()
    provider.property_mappings.set(scopes)
    provider.save()

    # ── application + group gate ───────────────────────────────────────
    app, _ = Application.objects.get_or_create(slug=SLUG, defaults=dict(name=APP_NAME))
    app.name = APP_NAME
    app.provider = provider
    app.save()
    PolicyBinding.objects.get_or_create(target=app, group=group, defaults=dict(order=0, enabled=True))

    print("SETUP_OK")
    print(f"OIDC_CLIENT_ID={provider.client_id}")
    print(f"OIDC_CLIENT_SECRET={provider.client_secret}")
except Exception:  # noqa: BLE001 - surface the full traceback for debugging
    print("SETUP_FAILED")
    traceback.print_exc()
