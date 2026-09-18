import os
import time

from dotenv import load_dotenv
from google import genai


load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


def generate_text(prompt: str):

    for attempt in range(3):

        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt
            )

            return response.text

        except Exception as e:
            print(f"Attempt {attempt + 1} failed:")
            print(e)

            if attempt < 2:
                time.sleep(5)

    raise Exception("Gemini unavailable after retries")