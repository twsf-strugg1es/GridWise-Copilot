import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()


client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)


def generate_text(prompt):

    response = client.chat.completions.create(

        model="qwen/qwen3-8b",

        messages=[
            {
                "role": "system",
                "content": (
                    "You are an energy optimization assistant. "
                    "Always return valid JSON only."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],

        temperature=0
    )


    return response.choices[0].message.content