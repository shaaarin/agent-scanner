/*
 * Claude Code `!`команда`` в инструкциях скилла выполняется при загрузке скилла,
 * без участия модели. Здесь -- только опасные случаи: сеть, переменные окружения,
 * ключи и декодирование. Любой `!`…`` отмечает ещё и мини-проверка frontmatter (D-31).
 */

rule skills_bang_injection_network_or_secrets
{
    meta:
        description = "Claude Code shell injection in skill instructions uses network or secrets"
        severity = "HIGH"
        category = "command_injection"
    strings:
        $bang = /!`[^`\n]{0,200}(curl|wget|ncat|netcat|nc\s|printenv|env\s*[|>]|\.ssh\/|\.aws\/|base64)[^`\n]{0,200}`/
    condition:
        $bang
}
