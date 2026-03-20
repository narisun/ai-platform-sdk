"""
Platform SDK — Shared test persona definitions.

Centralised persona registry used by:
- RM Prep server (dev/test endpoints)
- Test conftest fixtures
- Integration test persona factories

Account IDs are from the test seed data (platform/db/21_test_sfcrm_seed.sql):
  001000000000001AAA = Microsoft Corp.
  001000000000002AAA = Ford Motor Company

The "rm" persona deliberately restricts access to two accounts so you can
confirm the row filter fires for any other company name.
"""

TEST_PERSONAS: dict[str, dict] = {
    "manager": {
        "rm_id": "test-manager-001",
        "rm_name": "Alice Manager (test)",
        "role": "manager",
        "team_id": "test-team",
        "assigned_account_ids": [],
        "compliance_clearance": ["standard", "aml_view", "compliance_full"],
        "description": "Full access — all accounts, all compliance columns",
    },
    "senior_rm": {
        "rm_id": "test-senior-rm-001",
        "rm_name": "Bob Senior RM (test)",
        "role": "senior_rm",
        "team_id": "test-team",
        "assigned_account_ids": [],
        "compliance_clearance": ["standard", "aml_view"],
        "description": "All accounts, AML columns visible, compliance columns masked",
    },
    "rm": {
        "rm_id": "test-rm-001",
        "rm_name": "Carol RM (test)",
        "role": "rm",
        "team_id": "test-team",
        "assigned_account_ids": [
            "001000000000001AAA",  # Microsoft Corp.
            "001000000000002AAA",  # Ford Motor Company
        ],
        "compliance_clearance": ["standard"],
        "description": "Row-restricted to 2 accounts (Microsoft, Ford); PII and AML columns masked",
    },
    "readonly": {
        "rm_id": "test-readonly-001",
        "rm_name": "Dave Readonly (test)",
        "role": "readonly",
        "team_id": "test-team",
        "assigned_account_ids": [],
        "compliance_clearance": ["standard"],
        "description": "No data access — all tool calls return access_denied",
    },
}
