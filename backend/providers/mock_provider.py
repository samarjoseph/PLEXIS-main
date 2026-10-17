import json
from providers.base import BaseProvider, ProviderResponse
import logging
logger = logging.getLogger(__name__)

class MockProvider(BaseProvider):
    def __init__(self, metadata):
        self.metadata = metadata
    
    @property
    def provider_name(self) -> str:
        return "mock"

    def generate(self, *args, **kwargs):
        prompt_obj = kwargs.get('prompt') if 'prompt' in kwargs else (args[0] if len(args) > 0 else "")
        last_msg = ""
        
        if hasattr(prompt_obj, "messages") and isinstance(prompt_obj.messages, list) and len(prompt_obj.messages) > 0:
            last_msg = str(getattr(prompt_obj.messages[-1], "content", getattr(prompt_obj.messages[-1], "text", str(prompt_obj.messages[-1])))).lower()
        elif hasattr(prompt_obj, "prompt"):
            last_msg = str(prompt_obj.prompt).lower()
        else:
            last_msg = str(prompt_obj).lower()

        logger.info(f"MOCK RAW: {last_msg[:100]}...{last_msg[-100:]}")

        # Look for user query explicitly
        import re
        match = re.search(r'user query:\s*\\?"([^\\"]+)\\?"', last_msg)
        if not match:
            match = re.search(r'user:\s*(.*?)(?:\\n|\n|})', last_msg)
            
        query = ""
        if match:
            query = match.group(1).lower()
            
        logger.info(f"MOCK EXTRACTED EXACT QUERY: {query}")

        if "how many rows" in query:
            return ProviderResponse(text=json.dumps({"intent": "DATA_OPERATION", "operations": [{"type": "COUNT"}], "confidence": 0.99, "reason": "mock"}), model="mock", provider="mock")
        if "how many columns" in query:
            return ProviderResponse(text=json.dumps({"intent": "DATA_OPERATION", "operations": [{"type": "GET_SCHEMA"}], "confidence": 0.99, "reason": "mock"}), model="mock", provider="mock")
        if "what are all the column names" in query:
            return ProviderResponse(text=json.dumps({"intent": "DATA_OPERATION", "operations": [{"type": "GET_SCHEMA"}], "confidence": 0.99, "reason": "mock"}), model="mock", provider="mock")
        if "what are the data types" in query:
            return ProviderResponse(text=json.dumps({"intent": "DATA_OPERATION", "operations": [{"type": "GET_SCHEMA"}], "confidence": 0.99, "reason": "mock"}), model="mock", provider="mock")
        
        return ProviderResponse(text=json.dumps({"intent": "conversation", "reason": "mock fallback", "confidence": 0.5}), model="mock", provider="mock")

    def generate_json(self, *args, **kwargs):
        return self.generate(*args, **kwargs)

    def health_check(self) -> bool:
        return True

    async def generate_async(self, *args, **kwargs):
        pass
    def generate_stream(self, *args, **kwargs):
        pass
    async def generate_stream_async(self, *args, **kwargs):
        pass
