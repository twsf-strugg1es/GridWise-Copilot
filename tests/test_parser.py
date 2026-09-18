from backend.llm.parser import parse_operator_note


result = parse_operator_note(
    "Do not charge battery between 2 PM and 4 PM",
    0
)

print(result)