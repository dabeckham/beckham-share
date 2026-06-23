#!/usr/bin/env sh
# Post-deploy smoke + configuration verification against the LIVE deployment.
# Run on the host. Exits non-zero on the first failure. This is the gate that
# checks the things integration tests can't: real TLS, real routing across all
# hostnames, a true upload->download round-trip, and the Authentik provider
# configuration (grant_types + redirect_uris) that the login flow depends on.
set -eu

BASE="${SMOKE_BASE:-https://share.beckham.ai}"
HOSTS="share dropbox buckets"
fail() { echo "SMOKE FAIL: $1"; exit 1; }

echo ">> health on all hosts"
for h in $HOSTS; do
  code=$(curl -sS -m 15 -o /dev/null -w '%{http_code}' "https://$h.beckham.ai/healthz") || fail "$h unreachable"
  [ "$code" = "200" ] || fail "$h /healthz = $code"
  echo "   $h ok"
done

echo ">> anonymous upload -> share -> download round-trip"
tmp=$(mktemp); echo "smoke-test-$(date +%s)" > "$tmp"
resp=$(curl -sS -m 30 -F "file=@$tmp" -F "fp=smoke" "$BASE/api/anon-upload")
token=$(printf '%s' "$resp" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
[ -n "$token" ] || fail "no token in upload response: $resp"
printf '%s' "$resp" | grep -q "\"share_url\":\"$BASE/s/$token\"" || fail "share_url malformed: $resp"
[ "$(curl -sS -m 15 -o /dev/null -w '%{http_code}' "$BASE/s/$token")" = "200" ] || fail "share page not 200"
got=$(curl -sS -m 15 "$BASE/d/$token")
[ "$got" = "$(cat "$tmp")" ] || fail "download bytes mismatch"
rm -f "$tmp"
echo "   round-trip ok (token $token)"

echo ">> canonical redirect (dropbox/app -> share)"
loc=$(curl -sS -m 15 -o /dev/null -w '%{redirect_url}' "https://dropbox.beckham.ai/app")
[ "$loc" = "https://share.beckham.ai/app" ] || fail "canonical redirect = $loc"
echo "   ok"

echo ">> TLS issued by Let's Encrypt"
echo | openssl s_client -connect share.beckham.ai:443 -servername share.beckham.ai 2>/dev/null \
  | openssl x509 -noout -issuer 2>/dev/null | grep -qi "let's encrypt" || fail "unexpected cert issuer"
echo "   ok"

echo ">> Authentik provider config (grant_types + redirect_uris)"
cfg=$(cd "$HOME/idp" && docker compose exec -T authentik-server ak shell 2>/dev/null <<'PY' | grep '^CFG:'
from authentik.providers.oauth2.models import OAuth2Provider
p = OAuth2Provider.objects.get(name="beckham-share")
print("CFG:grant_types=" + ",".join(p.grant_types))
print("CFG:redirects=" + " ".join(str(u.url) for u in p.redirect_uris))
PY
)
echo "$cfg" | grep -q "grant_types=.*authorization_code" || fail "provider missing authorization_code grant"
echo "$cfg" | grep -q "share.beckham.ai/auth/callback" || fail "provider missing share callback URI"
echo "   $(echo "$cfg" | tr '\n' ' ')"

echo "SMOKE OK"
