"""
Enhanced warmth and personality test for Plexis Conversation Engine.
Tests: greetings, compliments, achievements, emoji usage, curiosity, casual chat.
"""

import sys
import requests
import time
import uuid

sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://localhost:5000/api/ask"

def ask(message, session_id=None):
    sid = session_id or str(uuid.uuid4())
    resp = requests.post(BASE_URL, json={"message": message}, headers={"X-Session-Id": sid}, timeout=30)
    return resp.json().get("answer", "[ERROR]"), sid

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def chat(label, message, session_id=None):
    answer, sid = ask(message, session_id)
    print(f"User: {message}")
    print(f"Plexis: {answer}\n")
    return sid

time.sleep(3)  # wait for server

section("TEST 1 — GREETING (warm & emoji)")
chat("Hello", "Hi!")

section("TEST 2 — COMPLIMENT HANDLING")
chat("Compliment", "You are so cute!")
chat("Compliment 2", "You're amazing, Plexis!")

section("TEST 3 — CELEBRATING AN ACHIEVEMENT")
sid = str(uuid.uuid4())
chat("Build up", "I've been trying to fix this bug for 3 hours...", sid)
time.sleep(2)
chat("Win!", "BRO I FINALLY FIXED IT!", sid)

section("TEST 4 — ENCOURAGEMENT WHEN STRUGGLING")
chat("Struggle", "I don't understand machine learning at all. It's so confusing.")

section("TEST 5 — CASUAL CHAT")
chat("Casual", "What's your favorite thing to do?")

section("TEST 6 — CURIOSITY TRIGGER")
chat("Curiosity", "I just started learning piano.")

section("TEST 7 — HUMOR")
chat("Humor", "If you were a pizza topping, what would you be?")

section("TEST 8 — OPINIONS")
chat("Opinion", "What do you think about Python?")
