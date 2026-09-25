import requests
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

session = requests.Session()

def ask(msg):
    headers = {'X-Session-Id': 'test-session-123'}
    r = session.post('http://localhost:5000/api/ask', json={'message': msg}, headers=headers)
    print(f"User: {msg}")
    print(f"Plexis: {r.json().get('answer')}\n")
    time.sleep(15)

print("--- TESTING REPETITION OBSERVATION ---")
ask("Hi")
ask("Hi")
ask("Hi")

print("--- TESTING CURIOSITY ---")
ask("I just bought a telescope.")

print("--- TESTING MOOD/HUMOR INFERENCE ---")
ask("Give me 10 emojis.")

print("--- TESTING SMALL OPINIONS ---")
ask("What do you think about Python?")
