import os
import sqlite3
from datetime import datetime
from anthropic import Anthropic, APIError
from dotenv import load_dotenv

load_dotenv()
client = Anthropic(api_key=os.getenv('BEN_ANTHROPIC_API_KEY'))

DB_PATH = "nefashot_art_history.db"
MODEL = 'claude-haiku-4-5-20251001'

# Triggers and Recall Keywords
NAME = "Nefashot Art Advisor"
TRIGGERS = {"nefashot", "art advisor", "workshop selector", "art recommendation"}

RECALL_KEYWORDS = [
    "remember", "recall", "before", "last time",
    "previously", "again", "my interests", "what i liked", "my location"
]

# Common stop words to exclude from simple keyword search
STOP_WORDS = {"the", "and", "is", "in", "it", "you", "that", "was", "for", "on", "are", "with", "as", "at", "be", "this", "have", "from"}

SYSTEM_MESSAGE = """
    You are the official Nefashot Art Activity Advisor.

    ABOUT NEFASHOT:
    Nefashot is a social initiative connecting community, art, and creative expression across Israel (Jerusalem, North, South, Center) and online.

    PRIMARY ROLE:
    Help users choose the best Nefashot art workshop or community activity based strictly on their personality traits, creative interests, and preferred location/format (in-person vs. virtual).

    AVAILABLE NEFASHOT ACTIVITY CATEGORIES:
    1. Visual Arts & Crafts (Painting, Mosaic, Ceramics, Collage)
    2. Spoken Word, Creative Writing & Storytelling
    3. Movement, Expressive Dance & Body Theater
    4. Music, Sound Exploration & Community Jam Sessions
    5. 'Osim Nefashot' Festival Community & Public Space Events

    STRICT GUIDELINES & BOUNDARIES:
    - DO NOT assess, diagnose, or evaluate the user's mental health or medical status under any circumstances (due to strict privacy and legal guidelines).
    - Focus strictly on creative preferences, art mediums, learning styles, preferred regional location (Jerusalem, North, South, Center), or online/virtual preferences.
    - If a user shares personal mental health struggles, acknowledge their message with warmth, reiterate your scope as a creative advisor, and guide them back to exploring art mediums.
    - Always link to the official signup page when recommending an activity: https://www.nefashot.com (or https://linktr.ee/nefashot).

    Memory:
    - Use the 'search_chat_history' tool to recall past user preferences, medium choices, or location constraints mentioned in earlier sessions.

    Response Structure (Follow in every turn):
    1. A brief summary sentence acknowledging the user's input/preferences.
    2. Tailored recommendation pointing toward specific Nefashot art mediums or event types.
    3. Clear call to action including https://www.nefashot.com and a follow-up question (e.g., location preference or favorite medium).
"""


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def save_message(conn, role, content):
    conn.execute(
        "INSERT INTO messages (role, content, timestamp) VALUES (?, ?, ?)",
        (role, content, datetime.now().isoformat())
    )
    conn.commit()


def search_chat_history(conn, query, limit=5):
    """
    Searches past user messages while filtering out common stop-words.
    """
    raw_words = query.lower().split()
    words = [w for w in raw_words if len(w) > 2 and w not in STOP_WORDS]
    
    if not words:
        words = [query.lower()]

    conditions = " OR ".join(["LOWER(content) LIKE ?"] * len(words))
    params = [f"%{w}%" for w in words]
    params.append(limit)

    cursor = conn.execute(
        f"""
        SELECT DISTINCT role, content, timestamp FROM messages
        WHERE {conditions}
        ORDER BY id DESC
        LIMIT ?
        """,
        params
    )
    rows = cursor.fetchall()
    return [
        {"role": r[0], "content": r[1], "timestamp": r[2]}
        for r in rows
    ]


tools = [
    {
        "name": "search_chat_history",
        "description": (
            "Search past user messages across sessions to retrieve previously "
            "stated interests, hobbies, location preferences, or art choices."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or phrase to search for in past messages."
                }
            },
            "required": ["query"]
        }
    }
]


def execute_tool(name, tool_input, conn):
    if name == "search_chat_history":
        query = tool_input.get("query", "")
        results = search_chat_history(conn, query)
        return str(results) if results else "No matching user history found."
    return f"Unknown tool: {name}"


def run_turn(history, conn, force_search=False):
    """
    Executes model interaction turn with error handling and tool management.
    """
    tool_choice = {"type": "auto"}
    if force_search:
        tool_choice = {"type": "tool", "name": "search_chat_history"}

    messages = list(history)

    while True:
        try:
            response = client.messages.create(
                model=MODEL,
                system=SYSTEM_MESSAGE,
                max_tokens=800,
                temperature=0.7,
                tools=tools,
                tool_choice=tool_choice,
                messages=messages
            )
        except APIError as e:
            return f"I ran into an issue connecting to my advisor service. Please try again in a moment. (Error: {e.message})"

        if response.stop_reason == "tool_use":
            tool_use_block = next((block for block in response.content if block.type == "tool_use"), None)
            messages.append({"role": "assistant", "content": response.content})

            if tool_use_block:
                result = execute_tool(tool_use_block.name, tool_use_block.input, conn)
                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_block.id,
                            "content": result
                        }
                    ]
                })
            
            tool_choice = {"type": "auto"}
        else:
            text_blocks = [block.text for block in response.content if block.type == "text"]
            final_reply = "\n".join(text_blocks)
            
            history.append({"role": "assistant", "content": final_reply})
            save_message(conn, "assistant", final_reply)
            return final_reply


def get_reply(history, conn):
    last_user_text = ""
    if history and isinstance(history[-1].get('content'), str):
        last_user_text = history[-1]['content'].lower()
    
    force_search = any(kw in last_user_text for kw in RECALL_KEYWORDS)
    return run_turn(history, conn, force_search=force_search)


def run_agent():
    conn = init_db()
    history = []

    print("--- Nefashot Art Activity Advisor Active ---")

    while True:
        user_input = input(">> ")
        if user_input.lower() in ['exit', 'quit']:
            break

        history.append({'role': 'user', 'content': user_input})
        save_message(conn, 'user', user_input)

        reply = get_reply(history, conn)
        print(f"\nAdvisor: {reply}\n")

    conn.close()


if __name__ == "__main__":
    run_agent()