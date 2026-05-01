"""Environment isolation primitives.

Defines the canonical `ENVIRONMENT` value space and the `X-Environment`
HTTP header name used by the SDK's HTTP factory and auth dependencies.
"""
from __future__ import annotations

from typing import Literal

Environment = Literal["dev", "staging", "prod"]
"""Strict enum of supported runtime environments.

The SDK's loader, auth dependency, and registry all enforce this set.
A service whose `ENVIRONMENT` env var is missing or anything other than
one of these three values fails to start.
"""

ENV_HEADER = "X-Environment"
"""Name of the HTTP header used to stamp environment on internal traffic.

Outbound: stamped automatically by `make_internal_http_client(config)`.
Inbound:  validated by `make_api_key_verifier(environment=...)`.
Mismatch: 403 Forbidden.
"""
