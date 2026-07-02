from voice.prompts.dictation_prompt import build_user_prompt
from voice.prompts.personal_details_prompt import build_personal_details_user_prompt
from voice.services.transcribe_service import strip_fillers


def test_strip_fillers_removes_vocalized_hesitations():
    assert strip_fillers("Um, the participant was calm.") == "the participant was calm."
    assert strip_fillers("She was, uh, quite tired today.") == "She was, quite tired today."
    assert strip_fillers("Er, we went to the shops.") == "we went to the shops."
    assert strip_fillers("Ummm the medication uhh was given.") == "the medication was given."
    assert strip_fillers("So, um, erm, he had lunch.") == "So, he had lunch."


def test_strip_fillers_preserves_content_lookalikes():
    # "um/uh/er" embedded in real words must survive untouched.
    assert strip_fillers("We sat here in the museum.") == "We sat here in the museum."
    assert strip_fillers("He chewed gum during the album review.") == (
        "He chewed gum during the album review."
    )
    assert strip_fillers("The number was under the counter.") == (
        "The number was under the counter."
    )


def test_strip_fillers_keeps_meaningful_discourse_words():
    # These are NOT stripped — they can carry meaning in a clinical record.
    text = "He said he would like to, you know, hurt himself. Well, hmm, ah."
    assert "like" in strip_fillers(text)
    assert "you know" in strip_fillers(text)
    assert "Well" in strip_fillers(text)
    assert "hmm" in strip_fillers(text)


def test_strip_fillers_handles_valid_word_repetition():
    # "had had" (past perfect) is valid English — must not be collapsed.
    assert strip_fillers("He had had lunch before the shift.") == (
        "He had had lunch before the shift."
    )


def test_strip_fillers_empty_and_whitespace():
    assert strip_fillers("") == ""
    assert strip_fillers("   ") == ""
    assert strip_fillers("um uh er erm") == ""


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
