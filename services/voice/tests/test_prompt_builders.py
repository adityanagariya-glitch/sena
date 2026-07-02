from voice.prompts.dictation_prompt import build_user_prompt
from voice.prompts.personal_details_prompt import build_personal_details_user_prompt


def test_personal_details_prompt_drops_null_fields():
    current_fields = {
        "first_name": "Jane",
        "last_name": None,
        "preferred_language": "English",
        "interpreter_required": False,
        "email": None,
    }
    prompt = build_personal_details_user_prompt(
        transcript="My name is Jane",
        current_fields=current_fields,
        missing_fields=["last_name"],
        history=[],
    )

    assert "'first_name': 'Jane'" in prompt
    assert "'preferred_language': 'English'" in prompt
    assert "'interpreter_required': False" in prompt
    assert "last_name" not in prompt.split("STILL_MISSING")[0]
    assert "'email'" not in prompt


def test_personal_details_prompt_keeps_missing_and_history():
    prompt = build_personal_details_user_prompt(
        transcript="hello",
        current_fields={"first_name": None},
        missing_fields=["first_name", "phone"],
        history=[{"speaker": "participant", "text": "hi"}],
    )

    assert "STILL_MISSING" in prompt
    assert "'first_name', 'phone'" in prompt
    assert "RECENT_HISTORY_JSON" in prompt
    assert "hi" in prompt


def test_dictation_prompt_drops_empty_sections():
    session_snapshot = {
        "existing_draft": {
            "participant_state": "Calm and engaged.",
            "support_actions": "",
            "incidents_risks": "",
        },
        "section_coverage": {"participant_state": 1.0, "support_actions": 0.0, "incidents_risks": 0.0},
        "missing_topics": ["support_actions", "incidents_risks"],
    }
    prompt = build_user_prompt(
        transcript="Participant remained calm throughout.",
        session_snapshot=session_snapshot,
        history=[],
    )

    assert "Calm and engaged." in prompt
    assert "'support_actions': ''" not in prompt
    assert "'incidents_risks': ''" not in prompt
    # section_coverage and missing_topics still fully present
    assert "support_actions" in prompt
    assert "incidents_risks" in prompt


def test_dictation_prompt_keeps_all_sections_when_filled():
    session_snapshot = {
        "existing_draft": {"participant_state": "Fine", "support_actions": "Assisted with lunch"},
        "section_coverage": {"participant_state": 1.0, "support_actions": 1.0},
        "missing_topics": [],
    }
    prompt = build_user_prompt(
        transcript="More detail",
        session_snapshot=session_snapshot,
        history=[],
    )

    assert "Fine" in prompt
    assert "Assisted with lunch" in prompt
