from backend.llm.client import generate_text


response = generate_text(
    "Return only JSON: {\"status\":\"working\"}"
)

print(response)