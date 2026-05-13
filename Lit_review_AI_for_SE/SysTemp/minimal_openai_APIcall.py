"""Minimal/cheapest OpenAI API test"""
import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

response = client.chat.completions.create(
    model="gpt-4o-mini",  # Cheapest model
    messages=[{"role": "user", "content": "Hi"}]  # Minimal prompt
)

print(response.choices[0].message.content)
print(f"\nUsage: {response.usage.prompt_tokens} prompt tokens, {response.usage.completion_tokens} completion tokens")
