import json

from backend.llm.client import generate_text
from backend.llm.prompts import SYSTEM_PROMPT


def parse_operator_note(note: str, index: int):

    prompt = f"""
{SYSTEM_PROMPT}

Operator note:

"{note}"
"""

    response = generate_text(prompt)

    data = json.loads(response)

    # normalize time format
    adjustment = data.get(
        "structured_adjustment",
        {}
    )

    if "start_time" in adjustment:
        start = int(
            adjustment["start_time"].split(":")[0]
        )

        end = int(
            adjustment["end_time"].split(":")[0]
        )

        adjustment["hours"] = list(
            range(start, end)
        )

        adjustment.pop("start_time", None)
        adjustment.pop("end_time", None)

        data["structured_adjustment"] = adjustment

    return data