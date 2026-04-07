"""
AgentContext — JWT-based authorization context.

Carries the verified identity and permission claims for a single RM session.
Created once in the orchestrator from a verified JWT, then forwarded as a
HMAC-signed base64-JSON header on every MCP tool call.

Flow:
  Streamlit UI  →  POST /brief  →  Authorization: Bearer <JWT>
  Orchestrator  →  AgentContext.from_jwt(token)
  Orchestrator  →  MCPToolBridge(ctx=ctx)  →  X-Agent-Context: <base64>.<hmac>
  MCP server    →  AgentContext.from_header(raw)  [verifies HMAC before decode]
  MCP server    →  build_row_filters(ctx) / build_col_mask(ctx)  →  PostgreSQL

X-Agent-Context wire format
───────────────────────────
  <base64url(JSON payload)>.<hex(HMAC-SHA256(base64url(JSON payload), CONTEXT_HMAC_SECRET))>

Both segments are required.  from_header() raises ValueError if the signature
is absent or does not match — the middleware then falls through to anonymous()
which grants the minimum-privilege context (readonly / standard clearance).

CONTEXT_HMAC_SECRET should be a separate secret from JWT_SECRET so that a JWT
compromise alone is insufficient to forge MCP context headers.
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import json
import os
from typing import Any

JWT_ALGORITHM = "HS256"
_DEFAULT_DEV_SECRET = "dev-secret-change-in-prod"


def _get_jwt_secret() -> str:
    """Read JWT_SECRET at call time, not import time.

    This ensures monkeypatched env vars in tests and late-set Docker
    Compose variables are picked up correctly.
    """
    return os.environ.get("JWT_SECRET", _DEFAULT_DEV_SECRET)


def _get_hmac_secret() -> bytes:
    """Read CONTEXT_HMAC_SECRET at call time, falling back to JWT_SECRET.

    Defence-in-depth: set CONTEXT_HMAC_SECRET to a separate value in
    production so a JWT compromise alone cannot forge MCP context headers.
    """
    jwt_secret = _get_jwt_secret()
    return os.environ.get("CONTEXT_HMAC_SECRET", jwt_secret).encode()


def _get_previous_hmac_secret() -> bytes | None:
    """Read CONTEXT_HMAC_SECRET_PREVIOUS for dual-secret rotation windows.

    During secret rotation, both the current and previous secrets are accepted
    so services can be redeployed independently without coordinated downtime.
    Returns None if no previous secret is configured (normal operation).
    """
    prev = os.environ.get("CONTEXT_HMAC_SECRET_PREVIOUS", "")
    return prev.encode() if prev else None


def _get_previous_jwt_secret() -> str | None:
    """Read JWT_SECRET_PREVIOUS for dual-secret rotation windows."""
    return os.environ.get("JWT_SECRET_PREVIOUS") or None


def assert_secrets_configured(environment: str | None = None) -> None:
    """Refuse to proceed if secrets are still defaults in a prod environment.

    Call this during service startup (lifespan or __main__) to fail fast
    rather than serving requests with insecure defaults.

    Raises:
        RuntimeError: if JWT_SECRET is the default in a prod environment.
    """
    env = environment or os.environ.get("ENVIRONMENT", "prod")
    secret = _get_jwt_secret()
    if env == "prod" and secret == _DEFAULT_DEV_SECRET:
        raise RuntimeError(
            "JWT_SECRET has not been rotated from the default value in a "
            "prod environment.  Set JWT_SECRET to a strong random secret."
        )


def _sign(payload_b64: str) -> str:
    """Return hex HMAC-SHA256 of the base64 payload."""
    return hmac.new(_get_hmac_secret(), payload_b64.encode(), hashlib.sha256).hexdigest()


def _verify_and_split(raw: str) -> str:
    """
    Verify the HMAC signature and return the payload segment.

    Supports dual-secret verification during rotation windows:
    tries the current secret first, then falls back to the previous secret.

    Raises ValueError on missing separator, wrong length, or bad signature.
    Constant-time comparison prevents timing attacks.
    """
    parts = raw.split(".")
    if len(parts) != 2:
        raise ValueError("X-Agent-Context: expected <payload>.<sig>, got wrong segment count")
    payload_b64, sig = parts

    # Try current secret
    expected = _sign(payload_b64)
    if hmac.compare_digest(sig, expected):
        return payload_b64

    # Try previous secret (rotation window)
    prev_secret = _get_previous_hmac_secret()
    if prev_secret:
        expected_prev = hmac.new(prev_secret, payload_b64.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig, expected_prev):
            return payload_b64

    raise ValueError("X-Agent-Context: HMAC signature mismatch — possible forgery attempt")


# Compliance clearance levels (ordered from lowest to highest)
CLEARANCE_LEVELS = ["standard", "aml_view", "compliance_full"]

# Columns masked at each clearance level
# MCP servers call build_col_mask(ctx) to get the list for this session
_AML_COLUMNS = {"AMLRiskCategory", "RiskRating", "KYCStatus", "FraudMonitoringSegment"}
_COMPLIANCE_COLUMNS = {"SanctionsScreeningStatus", "PEPFlag", "BSAAMLProgramRating", "SanctionsComplianceStatus"}

# Role hierarchy (higher = more access)
ROLE_RANK: dict[str, int] = {
    "readonly": 0,
    "rm": 1,
    "senior_rm": 2,
    "manager": 3,
    "compliance_officer": 3,
}


@dataclasses.dataclass(frozen=True)
class AgentContext:
    """Verified and parsed identity + authorization claims for one RM session.

    Two layers of identity:
      - Service identity (rm_id, role, team_id): identifies the calling agent/service
      - User identity (user_email, user_role): identifies the authenticated human user
        from the OAuth provider (Auth0). Flows through the entire stack as part of
        the HMAC-signed context — never as plaintext tool parameters.

    user_role values: "admin", "analyst", "viewer" (from Auth0 custom claims)
    """

    rm_id: str
    rm_name: str
    role: str
    team_id: str
    assigned_account_ids: tuple[str, ...]  # empty tuple = no row restriction
    compliance_clearance: tuple[str, ...]

    # ── User identity (from OAuth provider) ──────────────────────────────────
    user_email: str = ""
    user_role: str = ""    # "admin" | "analyst" | "viewer"

    # Valid OAuth roles — enforced at construction and deserialization
    _VALID_USER_ROLES = frozenset({"admin", "analyst", "viewer", ""})

    def __post_init__(self) -> None:
        """Fail-closed: empty clearance defaults to minimum privilege (standard only)."""
        if not self.compliance_clearance:
            object.__setattr__(self, 'compliance_clearance', ('standard',))
        # Normalize unknown user_role to empty (minimum privilege)
        if self.user_role and self.user_role not in self._VALID_USER_ROLES:
            object.__setattr__(self, 'user_role', '')

    # ── Serialization ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "rm_id": self.rm_id,
            "rm_name": self.rm_name,
            "role": self.role,
            "team_id": self.team_id,
            "assigned_account_ids": list(self.assigned_account_ids),
            "compliance_clearance": list(self.compliance_clearance),
            "user_email": self.user_email,
            "user_role": self.user_role,
        }

    def to_header_value(self) -> str:
        """Encode as signed base64-JSON for the X-Agent-Context header.

        Format: <base64url(JSON)>.<hex(HMAC-SHA256)>
        """
        payload_b64 = base64.b64encode(json.dumps(self.to_dict()).encode()).decode()
        sig = _sign(payload_b64)
        return f"{payload_b64}.{sig}"

    @classmethod
    def from_header(cls, raw: str) -> "AgentContext":
        """Decode and verify the X-Agent-Context header value.

        Raises ValueError if the HMAC signature is missing or invalid.
        Callers (AgentContextMiddleware) should catch ValueError and fall
        back to AgentContext.anonymous() — which now grants minimum privilege.
        """
        payload_b64 = _verify_and_split(raw)
        data = json.loads(base64.b64decode(payload_b64))
        return cls(
            rm_id=data.get("rm_id", "unknown"),
            rm_name=data.get("rm_name", ""),
            role=data.get("role", "readonly"),
            team_id=data.get("team_id", ""),
            assigned_account_ids=tuple(data.get("assigned_account_ids", [])),
            compliance_clearance=tuple(data.get("compliance_clearance", ["standard"])),
            user_email=data.get("user_email", ""),
            user_role=data.get("user_role", ""),
        )

    @classmethod
    def from_jwt(cls, token: str) -> "AgentContext":
        """Verify and decode a JWT into an AgentContext.

        Supports dual-secret verification during rotation windows:
        tries the current JWT_SECRET first, then JWT_SECRET_PREVIOUS.
        Raises jwt exceptions on failure.
        """
        try:
            import jwt as pyjwt
        except ImportError:
            raise RuntimeError("PyJWT not installed — add pyjwt to requirements")

        # Try current secret
        try:
            payload = pyjwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        except pyjwt.InvalidSignatureError:
            # Try previous secret (rotation window)
            prev_secret = _get_previous_jwt_secret()
            if prev_secret:
                payload = pyjwt.decode(token, prev_secret, algorithms=[JWT_ALGORITHM])
            else:
                raise

        return cls(
            rm_id=payload["sub"],
            rm_name=payload.get("name", ""),
            role=payload.get("role", "rm"),
            team_id=payload.get("team_id", ""),
            assigned_account_ids=tuple(payload.get("assigned_account_ids", [])),
            compliance_clearance=tuple(payload.get("compliance_clearance", ["standard"])),
            user_email=payload.get("user_email", ""),
            user_role=payload.get("user_role", ""),
        )

    @classmethod
    def anonymous(cls) -> "AgentContext":
        """Minimum-privilege context used when no valid X-Agent-Context header is present.

        Grants readonly role and standard clearance only — no compliance columns,
        no AML columns, no assigned accounts.  Fail-closed: unknown identity → least access.

        For local development with full access, set AUTH_MODE=none in the orchestrator
        and pass an explicitly constructed AgentContext via MCPToolBridge, rather than
        relying on this fallback.
        """
        return cls(
            rm_id="anonymous",
            rm_name="Unauthenticated",
            role="readonly",
            team_id="",
            assigned_account_ids=(),
            compliance_clearance=("standard",),
        )

    # ── Authorization helpers ──────────────────────────────────────────────────

    @property
    def role_rank(self) -> int:
        return ROLE_RANK.get(self.role, 0)

    def can_access_account(self, account_id: str) -> bool:
        """Returns True if this context is allowed to view the given account."""
        if self.role in ("manager", "compliance_officer", "senior_rm"):
            return True
        return account_id in self.assigned_account_ids

    def build_row_filters_crm(self) -> dict[str, list[str]]:
        """
        Row-level filter for SFCRM queries.
        Standard RM: restrict to assigned accounts.
        Senior RM / Manager / Compliance: no restriction (empty filter = all rows).
        """
        if self.role in ("manager", "compliance_officer", "senior_rm"):
            return {}
        if self.assigned_account_ids:
            return {"Account": list(self.assigned_account_ids)}
        return {"Account": ["__DENY_ALL__"]}  # safety: deny if no accounts assigned

    def build_row_filters_payments(self, party_names: list[str] | None = None) -> dict[str, list[str]]:
        """
        Row-level filter for BankDW queries.
        Passes party names (resolved from account IDs externally) as the filter.
        Senior RM / Manager / Compliance: no restriction.
        """
        if self.role in ("manager", "compliance_officer", "senior_rm"):
            return {}
        if party_names:
            return {"fact_payments": party_names, "dim_party": party_names}
        return {"fact_payments": ["__DENY_ALL__"]}

    def build_col_mask(self) -> list[str]:
        """
        Column-level mask: list of column names to NULL-out.
        standard  → mask all AML + compliance columns
        aml_view  → mask only compliance_full columns
        compliance_full → no masking
        """
        clearance_set = set(self.compliance_clearance)
        masked: set[str] = set()
        if "compliance_full" not in clearance_set:
            masked |= _COMPLIANCE_COLUMNS
        if "aml_view" not in clearance_set:
            masked |= _AML_COLUMNS
        return list(masked)

    def has_clearance(self, level: str) -> bool:
        return level in self.compliance_clearance
