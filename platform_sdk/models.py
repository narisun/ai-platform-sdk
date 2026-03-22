"""
Platform SDK — Shared Pydantic response models for MCP tool outputs.

Defines typed data contracts for the boundary between MCP tool servers and
consuming agent nodes. Using shared models ensures:
- Serialization/deserialization consistency
- Backward-compatible schema evolution (via schema_version field)
- IDE autocompletion and type checking in consuming code
- Contract test generation

Error Envelope:
    ToolResponse wraps every MCP tool output in a typed envelope that
    consuming agents can parse reliably. The 'retryable' flag enables
    intelligent retry decisions in orchestrators.

Usage in MCP server:
    from platform_sdk.models import ToolResponse, ErrorDetail, make_tool_error

    # Success
    return ToolResponse(success=True, data={"summary": "..."}).model_dump_json()

    # Error
    return make_tool_error("TIMEOUT", "Query timed out", retryable=True).model_dump_json()

Usage in consuming agent node:
    from platform_sdk.models import ToolResponse

    response = ToolResponse.model_validate_json(raw_result)
    if response.success:
        data = response.data
    else:
        if response.error.retryable:
            # retry logic
        else:
            # fail or skip
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Structured Error Envelope
# ---------------------------------------------------------------------------

class ErrorDetail(BaseModel):
    """Structured error information for MCP tool failures."""

    code: str = Field(
        ..., description="Machine-readable error code (e.g., UNAUTHORIZED, TIMEOUT, SERVICE_UNAVAILABLE)"
    )
    message: str = Field(
        ..., description="Human-readable error description"
    )
    retryable: bool = Field(
        default=False,
        description="Whether the caller can retry this request"
    )
    retry_after_seconds: Optional[int] = Field(
        default=None,
        description="Suggested wait time before retry (seconds)"
    )


class ToolResponse(BaseModel):
    """Typed envelope for all MCP tool outputs.

    Every MCP tool should return a ToolResponse serialized as JSON.
    Consuming agents deserialize and check success/error uniformly.
    """

    success: bool = Field(..., description="Whether the tool call succeeded")
    data: Optional[dict[str, Any]] = Field(
        default=None, description="Tool output data on success"
    )
    error: Optional[ErrorDetail] = Field(
        default=None, description="Error details on failure"
    )
    schema_version: int = Field(
        default=1, description="Response schema version for backward compatibility"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 UTC timestamp of the response"
    )


# ---------------------------------------------------------------------------
# Helper constructors
# ---------------------------------------------------------------------------

def make_tool_success(data: dict[str, Any]) -> ToolResponse:
    """Create a successful ToolResponse."""
    return ToolResponse(success=True, data=data)


def make_tool_error(
    code: str,
    message: str,
    retryable: bool = False,
    retry_after_seconds: Optional[int] = None,
) -> ToolResponse:
    """Create a failed ToolResponse with structured error detail."""
    return ToolResponse(
        success=False,
        error=ErrorDetail(
            code=code,
            message=message,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
        ),
    )


# ---------------------------------------------------------------------------
# Domain-specific response models (MCP tool outputs)
# ---------------------------------------------------------------------------

class ContactSummary(BaseModel):
    """Contact information from CRM."""
    name: str
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None


class OpportunitySummary(BaseModel):
    """Sales opportunity from CRM."""
    name: str
    stage: Optional[str] = None
    amount: Optional[float] = None
    close_date: Optional[str] = None


class ActivitySummary(BaseModel):
    """Recent activity/interaction from CRM."""
    type: str
    subject: Optional[str] = None
    date: Optional[str] = None
    description: Optional[str] = None


class SalesforceSummaryData(BaseModel):
    """Structured output from the Salesforce MCP get_salesforce_summary tool."""
    schema_version: int = 1
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    industry: Optional[str] = None
    annual_revenue: Optional[float] = None
    contacts: list[ContactSummary] = Field(default_factory=list)
    opportunities: list[OpportunitySummary] = Field(default_factory=list)
    recent_activities: list[ActivitySummary] = Field(default_factory=list)
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    cases: list[dict[str, Any]] = Field(default_factory=list)


class PaymentVolume(BaseModel):
    """Payment volume summary by type (inbound/outbound)."""
    direction: str  # "inbound" or "outbound"
    transaction_count: int = 0
    total_amount: float = 0.0
    currency: str = "USD"


class CounterpartySummary(BaseModel):
    """Top counterparty by transaction volume."""
    name: str
    transaction_count: int = 0
    total_amount: float = 0.0


class PaymentSummaryData(BaseModel):
    """Structured output from the Payments MCP get_payment_summary tool."""
    schema_version: int = 1
    client_name: Optional[str] = None
    period_days: int = 360
    volumes: list[PaymentVolume] = Field(default_factory=list)
    status_breakdown: dict[str, int] = Field(default_factory=dict)
    top_counterparties: list[CounterpartySummary] = Field(default_factory=list)
    bank_diversity: list[dict[str, Any]] = Field(default_factory=list)
    trend: Optional[dict[str, Any]] = None
    compliance_profile: Optional[dict[str, Any]] = None


class NewsArticle(BaseModel):
    """Individual news article from search."""
    title: str
    url: Optional[str] = None
    published_date: Optional[str] = None
    source: Optional[str] = None
    snippet: Optional[str] = None
    relevance_score: Optional[float] = None


class NewsSummaryData(BaseModel):
    """Structured output from the News MCP search_company_news tool."""
    schema_version: int = 1
    company: Optional[str] = None
    articles: list[NewsArticle] = Field(default_factory=list)
    aggregate_signal: Optional[str] = None  # RISK, OPPORTUNITY, POSITIVE, NEUTRAL, NO_NEWS
    signal_rationale: Optional[str] = None
