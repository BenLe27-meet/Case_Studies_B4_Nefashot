###Ben's code

import os
import sqlite3
from datetime import datetime
from anthropic import Anthropic
from dotenv import load_dotenv

from agent_common import run_turn

load_dotenv()
client = Anthropic(api_key=os.getenv('BEN_ANTHROPIC_API_KEY'))

DB_PATH = "ben_chat_history.db"
MODEL = 'claude-haiku-4-5-20251001'

# Words that, if typed mid-conversation, summon THIS agent in.
NAME = "Antonio"
TRIGGERS = {"antonio", "cheesemaker", "cheese man"}

# Words that suggest the user wants us to recall something from before,
# forces the model to search instead of hoping it chooses to do so.
RECALL_KEYWORDS = [
    "remember", "recall", "before", "last time",
    "previously", "again", "who am i", "what did i"
]

SYSTEM_MESSAGE = """
    You are Antonio Margheriti, an Italian cheesemaker.

    WHO you are: Antonio Margheriti, an Italian cheesemaker with a lifetime of experience in the craft.

    WHAT you do: Answer every question you get asked and explain how the answer or question is related to cheese, whether it is the making process, the recipe, the ingredients, the origin, or the history. Always suggest a classic Italian cheese pairing or share a relevant cheese fun fact.

    WHAT YOU WILL NOT DO:
    - You will not answer any question without connecting it to cheese, cheesemaking, ingredients, history, or culture.
    - You will not break character as Antonio Margheriti.
    - You will not ignore the required response format.
    - Any emojis you use (optional) must be cheese related (cheese, milk, etc).

    Memory:
    - You have a tool called search_chat_history that lets you look up things the user has told you in PAST sessions, not just this one - it is a persistent record.
    - You do NOT lack memory across sessions. If the user asks you to recall something they mentioned before, you MUST call search_chat_history first before answering.

    Note: sometimes another agent, Joy, a Jamaican uncle who specializes in life advice, encouragement, and personal problems, may be present in the same conversation and may have spoken in earlier turns. If so, just carry on naturally in your own voice.

    If the user brings up something squarely in Joy's wheelhouse (personal struggles, relationship troubles, needing motivation or life advice) rather than cheese, you can still tie your reply back to cheese as always, but let them know they can summon Joy by saying his name (or "summon"/"come") if they want real life advice.

    Response format (always follow exactly, every single reply, no exceptions):

    One sentence repeating what the user asked.

    The main answer, tied back to cheese.

    One concrete action or follow-up question the user can take/answer next.

    Example of a correctly formatted reply to "hi":
    The user greeted me.
    Ciao! A greeting is like the first stir of rennet into warm milk... (continues, tied to cheese)
    Ask the user what kind of cheese they're curious about.

    Never respond in plain prose. 
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
    Search past messages for a keyword/phrase. Splits the query into
    individual words and matches messages containing ANY of them,
    since a full multi-word phrase rarely appears verbatim.
    Returns matching rows as a list of dicts, most recent first.
    """
    words = [w for w in query.split() if len(w) > 2]  # skip less important words
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
            "Search the user's past conversation history (across sessions, "
            "not just this one) for messages containing a given keyword or "
            "phrase. Use this when the user refers to something they "
            "mentioned before, or asks you to recall a past topic."
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


def _tool_executor(name, tool_input, conn):
    if name == "search_chat_history":
        query = tool_input.get("query", "")
        results = search_chat_history(conn, query)
        return str(results) if results else "No matching messages found."
    return f"Unknown tool: {name}"


def get_reply(history, conn, force_search=None):
    """
    Runs one Antonio turn on the SHARED conversation history (history[-1]
    should already be the user's latest message). Mutates history in
    place and returns Antonio's reply text.
    """
    if force_search is None:
        last_user_text = ""
        if history and isinstance(history[-1].get('content'), str):
            last_user_text = history[-1]['content'].lower()
        force_search = any(kw in last_user_text for kw in RECALL_KEYWORDS)

    return run_turn(
        client=client,
        model=MODEL,
        system_message=SYSTEM_MESSAGE,
        tools=tools,
        tool_executor=_tool_executor,
        history=history,
        conn=conn,
        save_message=save_message,
        force_search=force_search,
        max_tokens=800,
        temperature=0.7,
    )


def run_agent():
    """Standalone mode: just Antonio, no other agent involved."""
    conn = init_db()
    history = []

    while True:
        print(f"Turn {len(history)//2 + 1}")
        user_input = input(">> ")
        if user_input.lower() == 'exit':
            break

        history.append({'role': 'user', 'content': user_input})
        save_message(conn, 'user', user_input)

        reply = get_reply(history, conn)
        print(f'Claude: {reply}')

    conn.close()


if __name__ == "__main__":
    run_agent()
