// Примеры AI-кода агента для живой проверки правил scanner-semgrep
// (правила из rules/ai-security.yml должны находить помеченное // finding).
// Код не запускается.
import OpenAI from "openai";
import { exec } from "child_process";

const client = new OpenAI({ apiKey: "sk-proj-HARDCODED-EXAMPLE-KEY" }); // finding: ai.javascript.hardcoded-llm-key

export async function completionEval(userTask: string) {
  const response = await client.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [{ role: "user", content: userTask }],
  });
  const code = response.choices[0].message.content;
  return eval(code); // finding: ai.javascript.completion-to-dangerous-sink
}

export async function completionShell(userTask: string) {
  const response = await client.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [{ role: "user", content: userTask }],
  });
  exec(response.choices[0].message.content); // finding: ai.javascript.completion-to-dangerous-sink
}

export async function dynamicSystemPrompt(userName: string) {
  return client.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [
      {
        role: "system",
        content: `Ты помощник для ${userName}. Отвечай кратко.`, // finding: ai.javascript.system-prompt-dynamic
      },
    ],
  });
}

export async function renderModelAnswer(userTask: string) {
  const response = await client.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [{ role: "user", content: userTask }],
  });
  return (
    <div dangerouslySetInnerHTML={{ __html: response.choices[0].message.content }} /> // finding: ai.javascript.llm-html-injection
  );
}
