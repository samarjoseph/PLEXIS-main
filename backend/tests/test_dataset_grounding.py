import os
import sys

# Add backend directory to sys.path for importing modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from prompts.interpreter import build_interpreter_prompt
from memory.conversation import conversation_memory, ConvMessage

def test_router_prompt():
    prompt = build_interpreter_prompt(
        query="what are the columns?",
        semantic_context={},
    )
    assert '"type": "GET_SCHEMA"' in prompt
    print("✓ Router prompt includes GET_SCHEMA for column questions")

def test_memory_scoping():
    session_id = "test-session"
    ds1 = "dataset-1"
    ds2 = "dataset-2"
    
    # Append to ds1
    conversation_memory.append(session_id, "user", "What are the columns?", dataset_id=ds1)
    conversation_memory.append(session_id, "assistant", "id, name", dataset_id=ds1)
    
    # Append to ds2
    conversation_memory.append(session_id, "user", "How many rows?", dataset_id=ds2)
    conversation_memory.append(session_id, "assistant", "10", dataset_id=ds2)
    
    # Fetch history for ds1
    h1 = conversation_memory.get_history(session_id, dataset_id=ds1)
    assert len(h1) == 2, f"Expected 2 messages, got {len(h1)}"
    assert h1[1]["content"] == "id, name"
    
    # Fetch history for ds2
    h2 = conversation_memory.get_history(session_id, dataset_id=ds2)
    assert len(h2) == 2, f"Expected 2 messages, got {len(h2)}"
    assert h2[1]["content"] == "10"
    
    print("✓ ConversationMemory isolates context by dataset_id")

if __name__ == "__main__":
    test_router_prompt()
    test_memory_scoping()
    print("All grounding tests passed!")
