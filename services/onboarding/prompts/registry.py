# ruff: noqa
"""Auto-generated prompt registry. Loud lookups replace silent file misses.

TEMPLATE: the base system prompt.  STEPS: step_id -> rules text.
MODES: mode -> rules text.  Missing key -> KeyError at call site (by design).
"""
from __future__ import annotations

from collections.abc import Callable

from onboarding.voice.turn_payload import VisibleField

from .onboarding_system import TEMPLATE as TEMPLATE
from .steps.client.consent import PROMPT as _step_consent
from .steps.client.consent_overview import PROMPT as _step_consent_overview
from .steps.client.consent_review import PROMPT as _step_consent_review
from .steps.client.documents import PROMPT as _step_documents
from .steps.client.lifestyle_requirements import PROMPT as _step_lifestyle_requirements
from .steps.client.medical_information import PROMPT as _step_medical_information
from .steps.client.ndis_plan_details import PROMPT as _step_ndis_plan_details
from .steps.client.personal_information import PROMPT as _step_personal_information
from .steps.staff.staff_banking import PROMPT as _step_staff_banking
from .steps.staff.staff_case_note import PROMPT as _step_staff_case_note
from .steps.staff.staff_documents import PROMPT as _step_staff_documents
from .steps.staff.staff_personal_information import PROMPT as _step_staff_personal_information
from .steps.staff.staff_policies import PROMPT as _step_staff_policies
from .steps.staff.staff_role_information import PROMPT as _step_staff_role_information
from .modes.fresh import PROMPT as _mode_fresh
from .modes.update import PROMPT as _mode_update

STEPS: dict[str, str | Callable[[list[VisibleField]], str]] = {
    'consent': _step_consent,
    'consent_overview': _step_consent_overview,
    'consent_review': _step_consent_review,
    'documents': _step_documents,
    'lifestyle_requirements': _step_lifestyle_requirements,
    'medical_information': _step_medical_information,
    'medical': _step_medical_information,              # client short form
    'ndis_plan_details': _step_ndis_plan_details,
    'ndis_plan': _step_ndis_plan_details,              # client short form
    'personal_information': _step_personal_information,
    'lifestyle_requirements': _step_lifestyle_requirements,
    'participant_requirements': _step_lifestyle_requirements,  # fixture short form
    'staff_banking': _step_staff_banking,
    'staff_case_note': _step_staff_case_note,
    'staff_documents': _step_staff_documents,
    'staff_personal_information': _step_staff_personal_information,
    'staff_policies': _step_staff_policies,
    'staff_role_information': _step_staff_role_information,
}

MODES: dict[str, str] = {
    'fresh': _mode_fresh,
    'update': _mode_update,
}

