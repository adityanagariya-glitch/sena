"""
Response variation manager — handles Australian English phrase rotation.
Keeps system prompt small by moving response logic to code.
"""

import random
from typing import Optional

# Response templates for different scenarios
FIELD_CONFIRMATIONS = [
    "Brilliant, got that down.",
    "Ta, that's locked in.",
    "Perfect, all sorted.",
    "Legend, thanks for that.",
    "Cheers, I've got it.",
    "Too easy, moving on.",
    "Sweet, that's recorded.",
    "No worries, I've got you down for that.",
    "Right, bang on.",
    "Awesome, all good there.",
    "Fair dinkum, that works a treat.",
    "Ripper, got that locked away.",
]

ASK_NEXT_FIELD = [
    "Now, what's your phone number? Format doesn't matter, I'll sort it.",
    "Right then, phone number next — whatever format you've got it in.",
    "Alright mate, need your mobile. Doesn't have to be perfect.",
    "Keen to grab your phone number — just say it however you've got it.",
    "What's your contact number? No need to worry about the format.",
    "Next up — mobile number, easy one.",
    "Your phone would be handy. Don't stress about the dashes and that.",
    "Can you give me your contact number? I'll fix up any formatting.",
    "What's your phone, mate?",
    "Mobile number next?",
]

TRICKY_FIELDS = [
    "Date formats are a bit annoying, yeah? Just say it how you'd normally say it, I'll work it out.",
    "Addresses can be messy — just rattle off what you've got, I'll make sense of it.",
    "Don't worry about getting it exact, I can work with what you give me.",
    "Heaps of people trip up on dates, no dramas.",
    "Just rough it out, I'm pretty good at decoding these things.",
    "No stress, I've heard every way of saying it. Go for it.",
]

MISSED_FIELD = [
    "Hang on, I missed your last name there.",
    "Quick one — I didn't catch your surname.",
    "Sorry, what was your last name again?",
    "Just realised I need your surname, mate.",
    "My bad — what's your family name?",
    "Whoops, I skipped your surname. What is it?",
]

INFO_OUT_OF_ORDER = [
    "Nice, I'll note that down. While you're at it, what's your...",
    "Good info, cheers. And just while we're on a roll, your...",
    "Ace. Since we're chatting, might as well grab your...",
    "Yeah nah, good point. I'll grab that. What about your...",
]

CONFIRM_CRITICAL = [
    "Just to make sure I got it right — {value}. Correct?",
    "Cool, so that's {value}. Sound about right?",
    "Running it back — {value}. Yeah?",
    "Got it as {value}. Just double-checking, yeah?",
]

HESITANT_USER = [
    "No rush, take your time.",
    "Whatever you remember's fine, we can come back to it.",
    "No worries if you're not sure, just give it your best shot.",
    "Heaps of people can't remember exact dates, happens all the time.",
    "It's alright if you're not 100% sure, I can work with rough estimates.",
    "Don't stress, that's close enough.",
]

NEXT_SECTION = [
    "Right, that's the personal stuff sorted. Now let's grab your address details.",
    "Nice work. Alright, shifting gears — what's your home address?",
    "Brilliant. Moving on, I'll need your address. What's the street?",
    "Good stuff. Now then, where are you based? Street address?",
    "Ace. Next bit — can you give me your address? Street first.",
    "Cool beans. Your place is next — address?",
]

SKIP_FIELD = [
    "No worries, we can skip that for now. What about...?",
    "That's fine, we'll circle back if needed. What's your...?",
    "All good, not everyone has that info handy. Let's move on to...?",
    "No stress, that's not essential right now. How about your...?",
    "Not a drama, we can sort that later. What about...?",
]

INTERRUPTED = [
    "No drama, I'm all ears.",
    "Go for it, what's up?",
    "Fair dinkum, what were you saying?",
    "Yeah nah, I'm listening.",
    "Hold up, I got you. What's the go?",
    "All good, go ahead mate.",
    "Yep, I'm here. What is it?",
    "No worries, what's on your mind?",
]

CONFIRM_INTERRUPTION = [
    "Right, so you're saying...?",
    "Got it — so the thing is...?",
    "Yeah, I hear you. So basically...?",
    "Okay, just to make sure — you mean...?",
    "Gotcha. So what you're telling me is...?",
]

APPRECIATE_URGENT = [
    "Cheers for flagging that, that's important.",
    "Good on you for mentioning that, mate.",
    "Thanks for jumping in, I would've missed that.",
    "Fair point, glad you brought that up.",
    "Legend, good catch.",
]

RECOVERY_AFTER_INTERRUPT = [
    "Alright, back to where we were...",
    "Right then, moving on...",
    "Cool, so where were we...",
    "Good. Let's get back on track...",
    "Sweet, now that's sorted, your...",
]


class ResponseManager:
    """Manages response variation without bloating the system prompt."""

    def __init__(self):
        self.used_responses = {}  # Track used responses by type

    def _get_unused_response(self, response_list: list[str], response_type: str) -> str:
        """Pick a response, preferring ones not recently used."""
        if response_type not in self.used_responses:
            self.used_responses[response_type] = set()

        used = self.used_responses[response_type]

        # If we've used all responses, reset (allow repetition after full cycle)
        if len(used) >= len(response_list):
            used.clear()

        # Pick from unused responses
        unused = [r for r in response_list if r not in used]
        if unused:
            response = random.choice(unused)
            used.add(response)
            return response

        # Fallback: pick any (shouldn't happen)
        return random.choice(response_list)

    def confirm_field(self) -> str:
        """Generate field confirmation response."""
        return self._get_unused_response(FIELD_CONFIRMATIONS, "confirm")

    def ask_next_field(self, field_name: str = "phone number") -> str:
        """Generate 'ask for next field' response."""
        response = self._get_unused_response(ASK_NEXT_FIELD, "ask_next")
        # Swap placeholder if needed
        return response.replace("phone number", field_name)

    def tricky_field(self, field_type: str = "date") -> str:
        """Generate response for tricky fields (dates, addresses)."""
        return self._get_unused_response(TRICKY_FIELDS, "tricky")

    def missed_field(self) -> str:
        """Generate response when a field was missed."""
        return self._get_unused_response(MISSED_FIELD, "missed")

    def info_out_of_order(self, next_field: str) -> str:
        """Generate response when user gives info out of expected order."""
        response = self._get_unused_response(INFO_OUT_OF_ORDER, "ooo")
        return response.replace("your...", f"your {next_field}")

    def confirm_critical(self, value: str) -> str:
        """Generate confirmation for critical data."""
        template = self._get_unused_response(CONFIRM_CRITICAL, "critical")
        return template.replace("{value}", value)

    def hesitant_user(self) -> str:
        """Generate reassurance for hesitant user."""
        return self._get_unused_response(HESITANT_USER, "hesitant")

    def next_section(self, section_name: str = "address") -> str:
        """Generate transition to next section."""
        response = self._get_unused_response(NEXT_SECTION, "section")
        return response.replace("address", section_name)

    def skip_field(self, next_field: str) -> str:
        """Generate response when user skips a field."""
        response = self._get_unused_response(SKIP_FIELD, "skip")
        return response.replace("What about...?", f"What's your {next_field}?")

    def interrupted(self) -> str:
        """Generate interruption acknowledgment."""
        return self._get_unused_response(INTERRUPTED, "interrupt")

    def confirm_interruption(self) -> str:
        """Generate confirmation of what was said during interruption."""
        return self._get_unused_response(CONFIRM_INTERRUPTION, "confirm_int")

    def appreciate_urgent(self) -> str:
        """Generate appreciation for urgent info."""
        return self._get_unused_response(APPRECIATE_URGENT, "appreciate")

    def recovery_after_interrupt(self) -> str:
        """Generate recovery phrase after handling interruption."""
        return self._get_unused_response(RECOVERY_AFTER_INTERRUPT, "recovery")

    def reset_session(self) -> None:
        """Reset response tracking for new session."""
        self.used_responses.clear()
