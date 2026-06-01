"""Service adapters: Staff, Policy, error handling.

Export: StaffAdapter, PolicyAdapter, ServiceAdapter base class
"""
from adapters.base import ServiceAdapter
from adapters.staff_adapter import StaffAdapter
from adapters.policy_adapter import PolicyAdapter
from adapters.error_handler import handle_adapter_error, explain_error

__all__ = [
    "ServiceAdapter",
    "StaffAdapter",
    "PolicyAdapter",
    "handle_adapter_error",
    "explain_error",
]
