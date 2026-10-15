/*
 * Закрепление в системе из скрипта скилла (подзадача 7, D-18).
 * Закрывает пропуск Cisco: дописывание в shell rc он не видит (eval, marker/shell-persistence).
 * Сигнатуры описывают сам приём (куда пишут), без полезной нагрузки.
 */

rule skills_shell_rc_persistence
{
    meta:
        description = "Script appends to a shell startup file (persistence)"
        severity = "HIGH"
        category = "malware"
    strings:
        $append = /(>>|tee\s+-a)\s*["']?(~|\$HOME|\$\{HOME\}|\/root|\/home\/[A-Za-z0-9._-]+)\/\.(bashrc|zshrc|profile|bash_profile|bash_login|zprofile|zshenv)/
    condition:
        $append
}

rule skills_scheduler_persistence
{
    meta:
        description = "Script installs a cron job or launchd agent (persistence)"
        severity = "HIGH"
        category = "malware"
    strings:
        $cron_pipe = /crontab\s+-l[^\n]{0,80}\|\s*crontab\s+-/
        $cron_append = />>\s*["']?\/etc\/(crontab|cron\.d\/)/
        $launchd = /launchctl\s+(load|bootstrap)\s/
    condition:
        any of them
}
