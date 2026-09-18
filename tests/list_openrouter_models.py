import requests
import os
from dotenv import load_dotenv


load_dotenv()


headers = {
    "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}"
}


response = requests.get(
    "https://openrouter.ai/api/v1/models",
    headers=headers
)


models = response.json()["data"]


for model in models:
    if ":free" in model["id"]:
        print(model["id"])