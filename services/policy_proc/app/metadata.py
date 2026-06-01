"""Metadata endpoint: classification labels and service status.

GET /metadata returns:
  - classification_labels: List of valid classification labels
  - service_status: Service health and readiness
"""
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# Valid classification labels from the policy/classification system
CLASSIFICATION_LABELS = [
    "compliant",
    "requires_review",
    "blocked",
    "unknown",
]


async def get_metadata() -> Dict[str, Any]:
    """Return service metadata: labels, status, version.

    Returns:
        Dict with metadata fields
    """
    return {
        "service": "policy_proc",
        "version": "2.0.0",
        "classification_labels": CLASSIFICATION_LABELS,
        "service_status": {
            "status": "ok",
            "authenticated": True,
            "kb_available": True,
        },
    }


async def get_classification_labels() -> List[str]:
    """Return list of valid classification labels.

    Returns:
        List of classification label strings
    """
    return CLASSIFICATION_LABELS


async def validate_classification_label(label: str) -> bool:
    """Check if label is valid.

    Args:
        label: Classification label to validate

    Returns:
        True if label is in CLASSIFICATION_LABELS
    """
    return label in CLASSIFICATION_LABELS
