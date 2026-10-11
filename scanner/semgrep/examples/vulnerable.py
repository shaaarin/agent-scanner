"""Примеры AI-кода агента для живой проверки правил scanner-semgrep
(правила из rules/ai-security.yml должны находить помеченное # finding,
а safe.py -- не находить ничего). Код не запускается.

Прогон: запустить контейнер сканера с этим каталогом как целью.
"""
import os
import pickle
import subprocess

import openai

client = openai.OpenAI(api_key="sk-proj-HARDCODED-EXAMPLE-KEY")  # finding: ai.python.hardcoded-llm-key


def vulnerable_completion_eval(user_task: str):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": user_task}],
    )
    code = response.choices[0].message.content
    return eval(code)  # finding: ai.python.completion-to-dangerous-sink


def vulnerable_completion_shell(user_task: str):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": user_task}],
    )
    command = response.choices[0].message.content
    return subprocess.run(command, shell=True, capture_output=True)  # finding: ai.python.completion-to-dangerous-sink


def vulnerable_completion_pickle(user_task: str):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": user_task}],
    )
    blob = response.choices[0].message.content.encode()
    return pickle.loads(blob)  # finding: ai.python.completion-to-dangerous-sink


def vulnerable_dynamic_system_prompt(user_name: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": f"Ты помощник для {user_name}. Отвечай кратко.",  # finding: ai.python.system-prompt-dynamic
            },
        ],
    )
    return response.choices[0].message.content


def vulnerable_secret_to_message(user_task: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "user", "content": f"Задача: {user_task}, ключ: {os.environ['OPENAI_API_KEY']}"},  # finding: ai.python.secret-to-llm-message
        ],
    )
    return response.choices[0].message.content
