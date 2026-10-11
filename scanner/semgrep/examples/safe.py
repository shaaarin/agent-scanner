"""Безопасный образец для живой проверки правил scanner-semgrep: на этом
файле базовый AI-набор не должен давать ни одной находки."""
import os
import subprocess

import openai

SYSTEM_PROMPT = "Ты безопасный ассистент платформы. Отвечай кратко и по делу."

ALLOWED_COMMANDS = {"status": ["systemctl", "status"], "disk": ["df", "-h"]}


def make_client() -> openai.OpenAI:
    return openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def ask(task: str) -> str:
    client = make_client()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ],
    )
    return response.choices[0].message.content or ""


def run_allowed(command_name: str) -> bytes:
    command = ALLOWED_COMMANDS.get(command_name)
    if not command:
        raise ValueError("неизвестная команда")
    return subprocess.run(command, check=True, capture_output=True).stdout
