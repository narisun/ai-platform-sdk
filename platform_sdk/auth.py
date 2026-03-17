"""
AgentContext — JWT-based authorization context.

Carries the verified identity and permission claims for a single RM session.
Created once in the orchestrator from a verified JWT, then forwarded as a
base64-JSON header on every MCP tool call.

Flow:
  Streamlit UI  →  POST /brief  →  Authorization: Bearer <JWT>
  Orchestrator  →  AgentContext.from_jwt(token)
  Orchestrator  →  MCPToolBridge(ctx=ctx)  →  X-Agent-Context: <base64>
  MCP server    →  AgentContext.from_header(raw)
  MCP server    →  build_row_filters(ctx) / build_col_mask(ctx)  →  PostgreSQL
"""
from __future__ import annotations

import base64
import dataclasses
import json
import os
from typing import Any

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-in-prod")
JWT_ALGORITHM = "HS256"

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
    """Verified and parsed identity + authorization claims for one RM session."""

    rm_id: str
    rm_name: str
    role: str
    team_id: str
    assigned_account_ids: tuple[str, ...]  # empty tuple = no row restriction
    compliance_clearance: tuple[str, ...]

    # ── Serialization ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "rm_id": self.rm_id,
            "rm_name": self.rm_name,
            "role": self.role,
            "team_id": self.team_id,
            "assigned_account_ids": list(self.assigned_account_ids),
            "compliance_clearance": list(self.compliance_clearance),
        }

    def to_header_value(self) -> str:
        """Encode as base64-JSON for the X-Agent-Context header."""
        return base64.b64encode(json.dumps(self.to_dict()).encode()).decode()

    @classmethod
    def from_header(cls, raw: str) -> "AgentContext":
        """Decode from X-Agent-Context header value."""
        data = json.loads(base64.b64decode(raw))
        return cls(
            rm_id=data.get("rm_id", "unknown"),
            rm_name=data.get("rm_name", ""),
            role=data.get("role", "readonly"),
            team_id=data.get("team_id", ""),
            assigned_account_ids=tuple(data.get("assigned_account_ids", [])),
            compliance_clearance=tuple(data.get("compliance_clearance", ["standard"])),
        )

    @classmethod
    def from_jwt(cls, token: str) -> "AgentContext":
        """Verify and decode a JWT into an AgentContext. Raises jwt exceptions on failure."""
        try:
            import jwt as pyjwt
        except ImportError:
            raise RuntimeError("PyJWT not installed — add pyjwt to requirements")

        payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return cls(
            rm_id=payload["sub"],
            rm_name=payload.get("name", ""),
            role=payload.get("role", "rm"),
            team_id=payload.get("team_id", ""),
            assigned_account_ids=tuple(payload.get("assigned_account_ids", [])),
            compliance_clearance=tuple(payload.get("compliance_clearance", ["standard"])),
        )

    @classmethod
    def anonymous(cls) -> "AgentContext":
        """No-auth context for local development when AUTH_MODE=none."""
        return cls(
            rm_id="dev",
            rm_name="Dev User",
            role="manager",
            team_id="dev",
            assigned_account_ids=(),
            compliance_clearance=("standard", "aml_view", "compliance_full"),
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
