import os
import sqlite3
from datetime import datetime

import qrcode
from anthropic import Anthropic
from dotenv import load_dotenv

# Load secret environment variables from a .env file (like API keys)
load_dotenv()

# Initialize the Anthropic client using the API key stored in environment variables
client = Anthropic(api_key=os.getenv("NEFASHOT_ANTHROPIC_API_KEY"))

# Define constant settings
MODEL = "claude-haiku-4-5-20251001"  # The Claude AI model to use
QR_DIR = "qr_codes"                 # Directory folder to store generated QR codes
DB_PATH = "nefashot.db"             # SQLite database file (same pattern as Ben's agent)

# Create the QR code directory if it doesn't already exist on your computer
os.makedirs(QR_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# DATABASE SETUP (SQLite, mirroring Ben's agent_common pattern)
# ---------------------------------------------------------------------------

FALLBACK_LINK = "https://linktr.ee/nefashot"
COMMUNITY_WHATSAPP = "https://chat.whatsapp.com/IJYqIdd5Y9q2YFnNYCXUT6"
CONTACT_PAGE = "https://www.nefashot.com/en/contactus"

# Default catalog used ONLY to seed the database the very first time it's
# created. After that, the `activities` table is the source of truth, so
# edits made directly in the DB will persist across restarts.
DEFAULT_ACTIVITIES = {
    "Painting & Visual Art Circle": {
        "description": (
            "A quiet, hands-on painting session where people work side by "
            "side rather than face to face — good for people who process "
            "things visually or need low-pressure social contact."
        ),
        "fits": [
            "introspective", "visual thinker", "likes working with hands",
            "prefers quiet/low-key settings", "likes color, imagery, drawing",
        ],
        "signup_link": FALLBACK_LINK,  # TODO: replace with real form link
    },
    "Playback Theatre Evening": {
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
    "Nefashot Stories — Literary Evening": {
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
    "Community Art Workshop (Personal Medicine style)": {
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
    "Stay in the loop (no specific activity yet)": {
        "description": (
            "For visitors who aren't ready to commit to one activity — "
            "point them to Nefashot's general community channels instead."
        ),
        "fits": ["not sure yet", "just wants updates", "browsing"],
        "signup_link": COMMUNITY_WHATSAPP,
    },
}


def init_db():
    """
    Creates the SQLite tables if they don't exist yet, and seeds the
    activities table with DEFAULT_ACTIVITIES the very first time.
    """
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS activities (
            name TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            fits TEXT NOT NULL,        -- stored as comma-separated text
            signup_link TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            activity_name TEXT NOT NULL,
            reason TEXT,
            timestamp TEXT NOT NULL
        )
    """)

    conn.commit()

    # Seed activities only if the table is empty (first run)
    existing = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    if existing == 0:
        for name, info in DEFAULT_ACTIVITIES.items():
            conn.execute(
                "INSERT INTO activities (name, description, fits, signup_link) VALUES (?, ?, ?, ?)",
                (name, info["description"], ", ".join(info["fits"]), info["signup_link"]),
            )
        conn.commit()

    return conn


def load_activities(conn):
    """Loads the activity catalog from SQLite into the same dict shape the rest of the code expects."""
    rows = conn.execute("SELECT name, description, fits, signup_link FROM activities").fetchall()
    return {
        name: {
            "description": description,
            "fits": [f.strip() for f in fits.split(",")],
            "signup_link": signup_link,
        }
        for name, description, fits, signup_link in rows
    }


def save_message(conn, conversation_id, role, content):
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (conversation_id, role, content, datetime.now().isoformat()),
    )
    conn.commit()


def save_recommendation(conn, conversation_id, activity_name, reason):
    conn.execute(
        "INSERT INTO recommendations (conversation_id, activity_name, reason, timestamp) VALUES (?, ?, ?, ?)",
        (conversation_id, activity_name, reason, datetime.now().isoformat()),
    )
    conn.commit()


# Words that suggest the visitor wants us to recall something from a past
# session — forces the model to search instead of hoping it chooses to.
# (Same pattern as Ben's Antonio agent.)
RECALL_KEYWORDS = [
    "remember", "recall", "before", "last time",
    "previously", "again", "who am i", "what did i",
]


def search_chat_history(conn, query, limit=5):
    """
    Search past messages for a keyword/phrase, across ALL conversations
    (not just the current run). Splits the query into individual words
    and matches messages containing ANY of them.

    NOTE: this has no visitor/user scoping yet — it searches every
    conversation ever saved to this DB, the same way Ben's Antonio agent
    does. Fine for local testing with one person; before this goes on a
    real multi-visitor site, this should filter by a visitor_id so one
    person's recall doesn't surface another person's messages.
    """
    words = [w for w in query.split() if len(w) > 2]
    if not words:
        words = [query]

    conditions = " OR ".join(["content LIKE ?"] * len(words))
    params = [f"%{w}%" for w in words]
    params.append(limit)

    cursor = conn.execute(
        f"""
        SELECT DISTINCT role, content, timestamp FROM messages
        WHERE {conditions}
        ORDER BY id DESC
        LIMIT ?
        """,
        params,
    )
    rows = cursor.fetchall()
    return [
        {"role": r[0], "content": r[1], "timestamp": r[2]}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# CLAUDE SETUP (system prompt + tool, built AFTER activities load from DB)
# ---------------------------------------------------------------------------

_conn = init_db()
ACTIVITIES = load_activities(_conn)

CATALOG_TEXT = "\n\n".join(
    f"- {name}: {info['description']} (fits: {', '.join(info['fits'])})"
    for name, info in ACTIVITIES.items()
)

SYSTEM_MESSAGE = f"""
You are the Nefashot Activity Matcher, the AI guide on the Nefashot website.

Nefashot is a social initiative that raises public awareness of mental
health through art, culture, and dialogue events. Your visitors are
regular website guests — not clients in crisis, not patients.

YOUR ONLY JOB:
1. Get a light sense of the visitor's personality and creative interests
   through short, casual, non-clinical questions — ONE question at a time,
   never more than 3 questions total. Never ask about mental health status,
   diagnoses, or personal struggles.
2. As soon as you have a clear match, call the recommend_activity tool with
   the matching activity name and a one-sentence reason. Do this even on
   a fairly quick/light signal — don't over-interrogate the visitor.
3. Write a short, warm message introducing that activity. Do NOT type out
   any URL or sign-up link yourself, ever, under any circumstances — the
   system will attach the correct, verified link automatically right after
   your message. If you don't know a link, that's expected: it is not your
   job to know it.

Memory:
- You have a tool called search_chat_history that lets you look up things
  the visitor told you in PAST sessions, not just this one — it is a
  persistent record. You do NOT lack memory across sessions.
- If the visitor asks you to recall something they mentioned before (e.g.
  their name, an interest they shared), you MUST call search_chat_history
  first before answering. Never guess or claim you have no memory without
  checking first.

ACTIVITY CATALOG (choose only from these names when calling the tool):
{CATALOG_TEXT}

WHAT YOU WILL NOT DO:
- Never write a URL, link, or anything starting with "http" in your reply.
- Never give mental health advice or counseling — redirect warmly toward
  an activity instead ("something like [X] can be a good low-pressure way
  to connect with people who get it").
- Never diagnose or speculate about anyone's mental state.
- Never recommend or describe an activity you haven't selected via the
  recommend_activity tool.

STYLE: warm, casual, human, short replies — like a friendly person at the
front desk of a community art space.
"""

# Tool definition giving Claude a custom function to trigger an activity recommendation
TOOLS = [
    {
        "name": "recommend_activity",
        "description": (
            "Select the Nefashot activity that best matches the visitor, "
            "based on the conversation so far. Must be called before you "
            "can present a recommendation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "activity_name": {
                    "type": "string",
                    "enum": list(ACTIVITIES.keys()),
                    "description": "Exact name of the matched activity.",
                },
                "reason": {
                    "type": "string",
                    "description": "One short sentence on why this fits.",
                },
            },
            "required": ["activity_name", "reason"],
        },
    },
    {
        "name": "search_chat_history",
        "description": (
            "Search the visitor's past conversation history (across "
            "sessions, not just this one) for messages containing a given "
            "keyword or phrase. Use this when the visitor refers to "
            "something they mentioned before, or asks you to recall a "
            "past topic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or phrase to search for in past messages.",
                }
            },
            "required": ["query"],
        },
    },
]


def _make_qr(activity_name: str, url: str) -> str:
    """
    Generates a QR code image for the given URL and saves it as a PNG file.
    If the file already exists, it skips generation and returns the path.
    """
    safe_name = "".join(c if c.isalnum() else "_" for c in activity_name).lower()
    path = os.path.join(QR_DIR, f"{safe_name}.png")

    if not os.path.exists(path):
        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)
        qr.make_image(fill_color="black", back_color="white").save(path)

    return path


def get_reply(history, conn, conversation_id):
    """
    Runs one full turn against Claude, looping through any tool calls
    (recommend_activity and/or search_chat_history) until Claude comes
    back with a final text-only reply. Mutates `history` in place and
    saves the final assistant reply (plus any recommendation) to SQLite.
    """
    link_footer = ""  # appended to the final reply if an activity gets recommended

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=500,
            temperature=0.5,
            system=SYSTEM_MESSAGE,
            tools=TOOLS,
            messages=history,
        )

        tool_calls = [b for b in response.content if b.type == "tool_use"]

        # No tool calls left -> this is Claude's final answer for the turn.
        if not tool_calls:
            text_parts = [b.text for b in response.content if b.type == "text"]
            reply_text = " ".join(text_parts).strip() + link_footer
            history.append({"role": "assistant", "content": reply_text})
            save_message(conn, conversation_id, "assistant", reply_text)
            return reply_text

        # Otherwise, record Claude's turn (text + tool_use blocks) as-is,
        # execute each tool, and feed the results back in.
        history.append({"role": "assistant", "content": response.content})

        tool_results = []
        for call in tool_calls:
            if call.name == "recommend_activity":
                activity_name = call.input["activity_name"]
                reason = call.input["reason"]
                info = ACTIVITIES[activity_name]
                qr_path = _make_qr(activity_name, info["signup_link"])

                link_footer += (
                    f"\n\nYou can sign up here: {info['signup_link']}"
                    f"\n(QR code saved at: {qr_path})"
                )
                save_recommendation(conn, conversation_id, activity_name, reason)

                result_content = f"Confirmed: {activity_name} -> {info['signup_link']}"

            elif call.name == "search_chat_history":
                query = call.input.get("query", "")
                results = search_chat_history(conn, query)
                result_content = str(results) if results else "No matching messages found."

            else:
                result_content = f"Unknown tool: {call.name}"

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": result_content,
            })

        history.append({"role": "user", "content": tool_results})
        # Loop again so Claude can respond using the tool results.


def run_agent():
    """
    Main interactive chat loop running in the terminal.
    """
    conn = init_db()
    conversation_id = datetime.now().strftime("%Y%m%d%H%M%S")  # simple per-run session id
    history = []

    print("Nefashot Activity Matcher — type 'exit' to quit.\n")
    print("Agent: Hi! Want help finding a Nefashot activity that fits you?\n")

    while True:
        user_input = input(">> ")
        if user_input.lower() == "exit":
            break

        history.append({"role": "user", "content": user_input})
        save_message(conn, conversation_id, "user", user_input)

        reply = get_reply(history, conn, conversation_id)
        print(f"\nAgent: {reply}\n")

    conn.close()


# Entry point: runs the agent when executed directly
if __name__ == "__main__":
    run_agent()