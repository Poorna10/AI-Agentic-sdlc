"""Capability and feature-pack catalog: the knowledge the agents reason over."""
from __future__ import annotations

# Ordered by dependency. `marker` is a file whose presence proves the pack is installed.
PACKS: dict[str, dict] = {
    "core": {
        "title": "Core shortener",
        "version": "1.0.0",
        "requires": [],
        "marker": "shortener/service.py",
        "capabilities": ["create_link", "redirect", "custom_alias", "analytics", "health"],
        "endpoints": [
            ("POST", "/api/v1/links", [201, 409, 422]),
            ("GET", "/{code}", [307, 404]),
            ("GET", "/api/v1/links/{code}/stats", [200, 404]),
            ("GET", "/healthz", [200]),
        ],
        "touches": ["shortener/api.py", "shortener/service.py", "shortener/store.py",
                    "shortener/config.py", "shortener/errors.py"],
        "schema": ["links", "clicks"],
        "dependencies": ["fastapi", "uvicorn", "httpx", "pytest"],
        "risks": [
            {"id": "R-CORE-1", "scenario": "Short-code collision under load",
             "mitigation": "Unique PK + bounded retry (5) then 503", "validation": "service tests: alias conflict"},
            {"id": "R-CORE-2", "scenario": "SSRF / open redirect to internal hosts",
             "mitigation": "http(s) only; private, loopback and link-local IPs and internal suffixes rejected",
             "validation": "parametrised URL validation tests"},
            {"id": "R-CORE-3", "scenario": "Guessable codes allow enumeration",
             "mitigation": "secrets-based 62^7 codes", "validation": "uniqueness test + policy bans `random`"},
        ],
        "adrs": [
            {"id": "ADR-001", "decision": "SQLite with a single locked connection",
             "rationale": "Zero-ops, transactional, adequate for the prototype's single node",
             "alternatives": ["PostgreSQL (better scale-out, heavier ops)", "Redis (volatile by default)"],
             "tradeoff": "Single-writer; horizontal scaling needs a store swap behind LinkStore"},
            {"id": "ADR-002", "decision": "Redirect with 307 + Cache-Control: no-store",
             "rationale": "301/308 are cached by browsers and would hide clicks from analytics",
             "alternatives": ["301 permanent", "302"], "tradeoff": "Extra hop on every visit"},
            {"id": "ADR-003", "decision": "Layered api -> service -> store with `# [ext:*]` extension anchors",
             "rationale": "Features land as small reviewable patches instead of rewrites",
             "alternatives": ["Plugin framework"], "tradeoff": "Anchors are a convention that must be preserved"},
        ],
    },
    "expiry": {
        "title": "Link expiry and click budgets",
        "version": "1.1.0",
        "requires": ["core"],
        "marker": "shortener/lifecycle.py",
        "capabilities": ["expiry", "click_limit"],
        "endpoints": [],   # additive fields on existing endpoints; adds 410 responses
        "touches": ["shortener/api.py", "shortener/service.py", "shortener/store.py", "shortener/errors.py"],
        "schema": ["links"],
        "schema_change": "ALTER TABLE links ADD COLUMN expires_at, max_clicks (nullable, additive)",
        "dependencies": [],
        "risks": [
            {"id": "R-EXP-1", "scenario": "Migration breaks or loses existing links",
             "mitigation": "Additive nullable columns, idempotent PRAGMA-guarded migration; NULL = unlimited",
             "validation": "legacy-database migration test"},
            {"id": "R-EXP-2", "scenario": "Click budget overshoot under concurrent redirects",
             "mitigation": "Count+insert inside BEGIN IMMEDIATE transaction", "validation": "budget enforcement test"},
            {"id": "R-EXP-3", "scenario": "Clock skew makes links expire early/late",
             "mitigation": "Single injected clock; expiry stored as absolute epoch", "validation": "fake-clock tests"},
        ],
        "adrs": [
            {"id": "ADR-010", "decision": "Additive nullable columns instead of a new table",
             "rationale": "Keeps existing rows valid with zero backfill; trivially reversible",
             "alternatives": ["link_policies table", "full migration framework"],
             "tradeoff": "Wider links table; revisit if more per-link policy accumulates"},
            {"id": "ADR-011", "decision": "HTTP 410 Gone for expired and exhausted links",
             "rationale": "Distinguishes 'existed but is gone' from 404 for clients and crawlers",
             "alternatives": ["404", "403"], "tradeoff": "Reveals that a code once existed"},
        ],
    },
    "ratelimit": {
        "title": "Per-client rate limiting on link creation",
        "version": "1.2.0",
        "requires": ["core"],
        "marker": "shortener/ratelimit.py",
        "capabilities": ["rate_limit"],
        "endpoints": [],
        "touches": ["shortener/api.py", "shortener/config.py", "shortener/errors.py"],
        "schema": [],
        "dependencies": [],
        "params": {"rate_limit_per_minute": 30},
        "risks": [
            {"id": "R-RL-1", "scenario": "Limiter state is per-process: N replicas allow N x the limit",
             "mitigation": "Documented; move to a shared store (Redis) when scaling out", "validation": "limitation recorded"},
            {"id": "R-RL-2", "scenario": "Key-churn attack exhausts limiter memory",
             "mitigation": "Bounded bucket table with oldest-half eviction", "validation": "bounded-keys test"},
            {"id": "R-RL-3", "scenario": "Clients behind one NAT/proxy share a bucket",
             "mitigation": "Generous burst = per-minute rate; trusted-proxy header handling is future work",
             "validation": "limitation recorded"},
        ],
        "adrs": [
            {"id": "ADR-020", "decision": "In-process token bucket keyed by client address",
             "rationale": "No new infrastructure; O(1) per request; smooths bursts",
             "alternatives": ["Redis sliding window", "API gateway rate limiting"],
             "tradeoff": "Not shared across replicas; resets on restart"},
        ],
    },
    "blocklist": {
        "title": "Malicious destination blocklist",
        "version": "1.3.0",
        "requires": ["core"],
        "marker": "shortener/blocklist.py",
        "capabilities": ["blocklist"],
        "endpoints": [],
        "touches": ["shortener/service.py", "shortener/config.py", "shortener/errors.py"],
        "schema": [],
        "dependencies": [],
        "risks": [
            {"id": "R-BL-1", "scenario": "Static denylist goes stale and misses new phishing domains",
             "mitigation": "Config-driven list; threat-feed integration recorded as follow-up", "validation": "limitation recorded"},
            {"id": "R-BL-2", "scenario": "Suffix matching blocks innocent look-alike domains",
             "mitigation": "Match exact host or '.'-delimited subdomain only", "validation": "notevil.example test"},
        ],
        "adrs": [
            {"id": "ADR-030", "decision": "Enforce the denylist at creation time, not redirect time",
             "rationale": "Keeps the hot redirect path free of extra checks",
             "alternatives": ["Check on every redirect"],
             "tradeoff": "Links created before a domain is listed keep redirecting; needs a periodic re-scan"},
        ],
    },
    "secheaders": {
        "title": "Security response headers",
        "version": "1.4.0",
        "requires": ["core"],
        "marker": "shortener/headers.py",
        "capabilities": ["security_headers"],
        "endpoints": [],
        "touches": ["shortener/api.py"],
        "schema": [],
        "dependencies": [],
        "risks": [
            {"id": "R-SH-1", "scenario": "HSTS on a non-HTTPS deployment is ignored or confusing",
             "mitigation": "Header is only honoured over TLS; document TLS termination requirement", "validation": "docs"},
        ],
        "adrs": [
            {"id": "ADR-040", "decision": "Add nosniff/DENY/no-referrer/HSTS but no Content-Security-Policy",
             "rationale": "A strict CSP would break the bundled Swagger UI; API returns no HTML",
             "alternatives": ["Strict CSP with docs disabled"], "tradeoff": "Slightly weaker defence-in-depth"},
        ],
    },
}

PACK_ORDER = list(PACKS)

# capability -> (regex keywords, human title)
CAPABILITIES: dict[str, dict] = {
    "create_link": {"keywords": r"\bshort(en)? (links?|urls?)\b|\bcreate (short )?links?\b|\bshorten (a |the |long )*(url|link)s?\b",
                    "title": "Create short links"},
    "redirect": {"keywords": r"\bredirects? (to|the|users?)\b|\bredirected\b|\bvisit(s|ing)? (a |the )?short",
                 "title": "Redirect short links"},
    "custom_alias": {"keywords": r"\balias(es)?\b|\bcustom (code|slug)s?\b", "title": "Custom aliases"},
    "analytics": {"keywords": r"\banalytics?\b|\bclick (counts?|stats?|statistics)\b|\breferrers?\b",
                  "title": "Click analytics"},
    "health": {"keywords": r"\bhealth\b|\bliveness\b", "title": "Health endpoint"},
    "expiry": {"keywords": r"\bexpir\w*|\bttl\b|time[- ]to[- ]live|\bvalid for\b", "title": "Link expiry (TTL)"},
    "click_limit": {"keywords": r"max(imum)? (number of )?clicks|click (limit|budget)|stop working after .*clicks|one-time",
                    "title": "Click budget"},
    "rate_limit": {"keywords": r"rate[- ]?limit|\bthrottl\w*|\bflood\w*|\babus(e|es|ed|ive)\b", "title": "Rate limiting"},
    "blocklist": {"keywords": r"block ?list|deny ?list|black ?list|malicious|phishing|malware", "title": "Domain blocklist"},
    "security_headers": {"keywords": r"security headers?|\bhsts\b|x-frame|nosniff|clickjack", "title": "Security headers"},
}

CAPABILITY_TO_PACK = {cap: pack for pack, meta in PACKS.items() for cap in meta["capabilities"]}


def pack_closure(packs: set[str]) -> list[str]:
    """Add transitive `requires`, return in dependency order."""
    out: set[str] = set()
    stack = list(packs)
    while stack:
        p = stack.pop()
        if p not in out:
            out.add(p)
            stack.extend(PACKS[p]["requires"])
    return [p for p in PACK_ORDER if p in out]


# Contract metadata used by the contract-first API stage and by documentation.
API_META: dict[str, dict] = {
    "core": {"request_fields": ["url", "alias"],
             "api_changes": ["POST /api/v1/links, GET /{code}, GET /api/v1/links/{code}/stats, GET /healthz (new)"]},
    "expiry": {"request_fields": ["ttl_seconds", "max_clicks"],
               "api_changes": ["POST /api/v1/links accepts optional ttl_seconds and max_clicks (additive)",
                               "GET /{code} may return 410 (link_expired / click_limit_reached)"]},
    "ratelimit": {"request_fields": [],
                  "api_changes": ["POST /api/v1/links may return 429 with Retry-After (new failure mode)"]},
    "blocklist": {"request_fields": [],
                  "api_changes": ["POST /api/v1/links may return 422 domain_blocked (new failure mode)"]},
    "secheaders": {"request_fields": [], "api_changes": []},
}
