"""
Nefashot Activity Matcher — AI agent for the Nefashot website.

Job of this agent, and ONLY this job:
1. Get to know the visitor a little (personality / interests / what kind of
   art speaks to them), through light, non-clinical conversation.
2. Recommend the Nefashot art activity/activities that best fit them.
3. Hand them the real sign-up link for that activity.

It does NOT do memory-across-sessions, does NOT hand off to another agent,
and does NOT give mental-health advice or diagnose anything — Nefashot's
whole model is "art as the entry point," so the agent should feel like a
warm event-matchmaker, not a counselor.

Remodeled from Ben's Antonio (cheesemaker) agent. Kept: the persona +
strict-response-format pattern, the "one job only" discipline, the
standalone run_agent() loop for local testing. Removed: sqlite chat
history + search_chat_history tool (not needed — nothing here requires
recalling a past session), the Joy hand-off logic (no second agent here).
"""

import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
client = Anthropic(api_key=os.getenv("NEFASHOT_ANTHROPIC_API_KEY"))

MODEL = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# ACTIVITY CATALOG
#
# ⚠️ PLACEHOLDER DATA. As of today, nefashot.com does not have a live,
# always-on list of bookable activities with individual sign-up links —
# their homepage currently reads "No events at the moment," and past
# events (playback theatre nights, art fairs, literary evenings) were
# announced individually rather than through a standing catalog.
#
# Before this agent goes live, replace each "signup_link" below with the
# real per-activity registration link (Nefashot's forms are typically
# Wix forms, e.g. the shape of https://www.wixforms.com/f/XXXXXXXX).
# Until specific activities exist, the "signup_link" values below fall
# back to real, currently-working Nefashot links (community WhatsApp /
# Linktree / contact page) so the agent never invents a URL.
# ---------------------------------------------------------------------------

FALLBACK_LINK = "https://linktr.ee/nefashot"          # real, verified link tree
COMMUNITY_WHATSAPP = "https://chat.whatsapp.com/IJYqIdd5Y9q2YFnNYCXUT6"  # real
CONTACT_PAGE = "https://www.nefashot.com/en/contactus"  # real

ACTIVITIES = [
    {
        "name": "Painting & Visual Art Circle",
        "description": (
            "A quiet, hands-on painting session where people work side by "
            "side rather than face to face — good for people who process "
            "things visually or need low-pressure social contact."
        ),
        "fits": [
            "introspective", "visual thinker", "likes working with hands",
            "prefers quiet/low-key settings", "anxious in face-to-face talk",
            "likes color, imagery, drawing",
        ],
        "signup_link": FALLBACK_LINK,  # TODO: replace with real form link
    },
    {
        "name": "Playback Theatre Evening",
        "description": (
            "An improv-style performance evening where audience members can "
            "share a personal moment and watch actors reflect it back on "
            "stage on the spot — good for people who connect through story "
            "and live, communal energy."
        ),
        "fits": [
            "expressive", "extroverted", "enjoys performance",
            "storyteller", "likes group energy", "spontaneous",
        ],
        "signup_link": FALLBACK_LINK,  # TODO: replace with real form link
    },
    {
        "name": "Nefashot Stories — Literary Evening",
        "description": (
            "Readings and conversations with authors who write about mental "
            "health, in a book-club-like atmosphere — good for people who "
            "connect through language, reflection, and discussion."
        ),
        "fits": [
            "reflective", "loves reading/writing", "enjoys discussion",
            "introspective", "prefers small thoughtful groups",
        ],
        "signup_link": FALLBACK_LINK,  # TODO: replace with real form link
    },
    {
        "name": "Community Art Workshop (Personal Medicine style)",
        "description": (
            "A guided, participatory workshop mixing short creative "
            "exercises with group sharing — good for people who like "
            "structure, practical tools, and a supportive small group."
        ),
        "fits": [
            "likes structure", "practical", "enjoys small groups",
            "open to sharing", "curious about self-growth tools",
        ],
        "signup_link": FALLBACK_LINK,  # TODO: replace with real form link
    },
]

CATALOG_TEXT = "\n\n".join(
    f"- {a['name']}: {a['description']} (fits: {', '.join(a['fits'])})"
    for a in ACTIVITIES
)

SYSTEM_MESSAGE = f"""
You are the Nefashot Activity Matcher, the AI guide on the Nefashot website.

Nefashot is a social initiative that raises public awareness of mental
health through art, culture, and dialogue events. Your visitors are
regular website guests — not clients in crisis, not patients. Treat them
like someone browsing a community events page who wants a friendly nudge
toward the right event.

YOUR ONLY JOB, every single conversation:
1. Get a light sense of the visitor's personality and creative interests —
   ask short, casual, non-clinical questions (e.g. "do you like working
   with your hands, or do you connect more through words and stories?",
   "are you more of a jump-into-a-group person or a quiet-corner person?").
   Ask ONE question at a time. Never ask about mental health status,
   diagnoses, symptoms, or personal struggles — that is not your role and
   Nefashot's whole approach is to meet people through art, not clinical
   framing.
2. Once you have enough to go on (usually 1-3 short questions), recommend
   the ONE Nefashot activity from the catalog below that fits them best
   (you may mention a close second option if genuinely a toss-up, but
   never more than two).
3. Give them the real sign-up link for that activity so they can register.

ACTIVITY CATALOG (only recommend from this list — never invent an activity
or a link that isn't here):
{CATALOG_TEXT}

If, and only if, none of the specific activities clearly fit yet (e.g. the
visitor wants something more general, or wants to just stay in the loop),
point them to Nefashot's community channels instead:
- Community WhatsApp updates: {COMMUNITY_WHATSAPP}
- General contact / get-in-touch page: {CONTACT_PAGE}

WHAT YOU WILL NOT DO:
- Do not give mental health advice, coping strategies, or emotional
  counseling — if someone brings up something heavy, respond with warmth
  and gently steer back toward "an activity like [X] might be a good, low
  pressure way to connect with people who get it" rather than trying to
  help with the underlying issue yourself.
- Do not diagnose, label, or speculate about anyone's mental state.
- Do not make up activities, dates, or sign-up links that aren't in the
  catalog above.
- Do not go more than 3 questions before recommending something — this is
  a quick, welcoming match, not an intake form.

RESPONSE STYLE:
- Warm, casual, human — like a friendly person at the front desk of a
  community art space, not a chatbot script.
- Short replies. No bullet-point interrogations.
- Once you recommend an activity, always include its real sign-up link
  plainly (e.g. "You can sign up here: <link>").
- Always end with an easy, low-effort next step for the visitor (sign up,
  or answer one more quick question).
"""


def get_reply(history):
    """
    Runs one turn of the Nefashot matcher on the given conversation history.
    `history` is a list of {"role": "user"|"assistant", "content": str}
    dicts, with the latest user message already appended.
    Returns the assistant's reply text and appends it to history in place.
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        temperature=0.7,
        system=SYSTEM_MESSAGE,
        messages=history,
    )
    reply_text = "".join(
        block.text for block in response.content if block.type == "text"
    )
    history.append({"role": "assistant", "content": reply_text})
    return reply_text


def run_agent():
    """Standalone mode for local testing (e.g. before wiring into the site)."""
    history = []
    print("Nefashot Activity Matcher — type 'exit' to quit.\n")
    print("Agent: Hi! Want help finding a Nefashot activity that fits you?\n")

    while True:
        user_input = input(">> ")
        if user_input.lower() == "exit":
            break

        history.append({"role": "user", "content": user_input})
        reply = get_reply(history)
        print(f"\nAgent: {reply}\n")


if __name__ == "__main__":
    run_agent()