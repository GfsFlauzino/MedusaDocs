"""Login único (SSO) por OpenID Connect, opcional. Só biblioteca padrão.

Fluxo: authorization code + PKCE (S256), com state (contra CSRF, também amarrado a um cookie do navegador)
e nonce (contra reutilização do token). O ID token é validado por completo:
  • assinatura RS256 com a chave pública (JWKS) do provedor;
  • iss = emissor da descoberta, aud contém o client_id (e azp, se houver várias audiências);
  • exp e iat com tolerância de 2 minutos; nonce igual ao gerado no início do login.
Funciona com Microsoft Entra ID, Okta, Keycloak, Google, Auth0, Authentik, ADFS 2016+ e outros provedores OIDC.
"""
import base64, hashlib, hmac, json, secrets, ssl, time, urllib.error, urllib.parse, urllib.request

SKEW = 120
_cache = {}          # url → (expira_em, documento)
SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")   # DigestInfo SHA-256 (PKCS#1 v1.5)


class SSOError(ValueError):
    pass


def b64url_dec(s):
    s = str(s)
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def b64url_enc(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _get_json(url, timeout=10, ttl=3600, force=False):
    now = time.time()
    if not force and url in _cache and _cache[url][0] > now: return _cache[url][1]
    if not url.lower().startswith("https://") and not url.lower().startswith(("http://localhost", "http://127.0.0.1")):
        raise SSOError(f"O provedor precisa usar HTTPS: {url}")
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "medusa-docs-sso"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            doc = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SSOError(f"{url} respondeu HTTP {e.code}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SSOError(f"Não foi possível ler {url}: {e}")
    _cache[url] = (now + ttl, doc)
    return doc


def discover(issuer, force=False):
    issuer = issuer.rstrip("/")
    d = _get_json(f"{issuer}/.well-known/openid-configuration", force=force)
    for k in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not d.get(k): raise SSOError(f"Descoberta OIDC sem o campo {k}")
    if d["issuer"].rstrip("/") != issuer: raise SSOError(f"O emissor informado ({issuer}) difere do publicado pelo provedor ({d['issuer']})")
    return d


def redirect_uri(public_url):
    return public_url.rstrip("/") + "/api/sso/callback"


def start(cfg):
    """Retorna (url de autorização, state, nonce, verifier)."""
    d = discover(cfg["issuer"])
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = b64url_enc(hashlib.sha256(verifier.encode()).digest())
    q = {"response_type": "code", "client_id": cfg["client_id"], "redirect_uri": redirect_uri(cfg["public_url"]),
         "scope": cfg.get("scopes") or "openid email profile", "state": state, "nonce": nonce,
         "code_challenge": challenge, "code_challenge_method": "S256"}
    sep = "&" if "?" in d["authorization_endpoint"] else "?"
    return d["authorization_endpoint"] + sep + urllib.parse.urlencode(q), state, nonce, verifier


def _post_form(url, data, headers, timeout=15):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try: err = json.loads(e.read().decode("utf-8"))
        except ValueError: err = {}
        raise SSOError(f"O provedor recusou a troca do código (HTTP {e.code}{': ' + str(err.get('error_description') or err.get('error')) if err else ''})")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SSOError(f"Falha ao falar com o provedor: {e}")


def exchange(cfg, code, verifier):
    d = discover(cfg["issuer"])
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(cfg["public_url"]), "code_verifier": verifier}
    methods = d.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
    headers = {}
    if cfg.get("client_secret") and "client_secret_basic" in methods:
        cred = f"{urllib.parse.quote(cfg['client_id'], safe='')}:{urllib.parse.quote(cfg['client_secret'], safe='')}"
        headers["Authorization"] = "Basic " + base64.b64encode(cred.encode()).decode()
    else:
        data["client_id"] = cfg["client_id"]
        if cfg.get("client_secret"): data["client_secret"] = cfg["client_secret"]
    tok = _post_form(d["token_endpoint"], data, headers)
    if not tok.get("id_token"): raise SSOError("O provedor não devolveu id_token (o escopo openid está configurado?)")
    return tok, d


def _rsa_verify(n, e, signing_input, sig):
    k = (n.bit_length() + 7) // 8
    if len(sig) != k: return False
    m = pow(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big")
    digest = hashlib.sha256(signing_input).digest()
    expected = b"\x00\x01" + b"\xff" * (k - 3 - len(SHA256_PREFIX) - len(digest)) + b"\x00" + SHA256_PREFIX + digest
    return hmac.compare_digest(m, expected)


def _key_for(d, kid):
    for force in (False, True):              # chave nova (rotação): busca o JWKS de novo uma vez
        keys = _get_json(d["jwks_uri"], force=force).get("keys", [])
        for k in keys:
            if k.get("kty") == "RSA" and (kid is None or k.get("kid") == kid) and k.get("use", "sig") == "sig":
                return int.from_bytes(b64url_dec(k["n"]), "big"), int.from_bytes(b64url_dec(k["e"]), "big")
    raise SSOError("Chave de assinatura do token não encontrada no JWKS do provedor")


def validate_id_token(id_token, d, client_id, nonce):
    try:
        h64, p64, s64 = id_token.split(".")
        header, claims, sig = json.loads(b64url_dec(h64)), json.loads(b64url_dec(p64)), b64url_dec(s64)
    except (ValueError, TypeError):
        raise SSOError("id_token malformado")
    if header.get("alg") != "RS256": raise SSOError(f"Algoritmo de assinatura não suportado: {header.get('alg')} (use RS256)")
    n, e = _key_for(d, header.get("kid"))
    if not _rsa_verify(n, e, f"{h64}.{p64}".encode(), sig): raise SSOError("Assinatura do id_token inválida")
    now = time.time()
    if str(claims.get("iss", "")).rstrip("/") != d["issuer"].rstrip("/"): raise SSOError("Emissor do token inesperado")
    aud = claims.get("aud"); aud = aud if isinstance(aud, list) else [aud]
    if client_id not in aud: raise SSOError("O token não foi emitido para esta aplicação (aud)")
    if len(aud) > 1 and claims.get("azp") not in (None, client_id): raise SSOError("azp do token inválido")
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] < now - SKEW: raise SSOError("Token expirado")
    if isinstance(claims.get("iat"), (int, float)) and claims["iat"] > now + SKEW: raise SSOError("Token emitido no futuro (relógio do servidor?)")
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce): raise SSOError("nonce inválido")
    if not claims.get("sub"): raise SSOError("Token sem sub")
    return claims


def userinfo(d, access_token, sub):
    if not d.get("userinfo_endpoint") or not access_token: return {}
    req = urllib.request.Request(d["userinfo_endpoint"], headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10, context=ssl.create_default_context()) as r:
            info = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return {}
    return info if info.get("sub") == sub else {}


def claim(claims, path):
    """Lê uma claim, aceitando caminho com ponto (ex.: realm_access.roles)."""
    cur = claims
    for part in str(path or "").split("."):
        if not part: return None
        if not isinstance(cur, dict): return None
        cur = cur.get(part)
    return cur


def map_role(claims, cfg):
    """Perfil pelos grupos/papéis do provedor. None = sem regra que se aplique."""
    vals = claim(claims, cfg.get("role_claim"))
    vals = set(map(str, vals if isinstance(vals, list) else [vals] if vals else []))
    for role in ("admin", "editor", "viewer"):
        wanted = {x.strip() for x in str((cfg.get("role_map") or {}).get(role, "")).split(",") if x.strip()}
        if wanted & vals: return role
    return None
