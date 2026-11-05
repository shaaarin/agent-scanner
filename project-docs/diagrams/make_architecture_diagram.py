# -*- coding: utf-8 -*-
"""
Архитектурная диаграмма Agent Scanner для презентации (слайд 16:9).

Запуск:  python make_architecture_diagram.py
Выход:   architecture_agent_scanner.png / .svg рядом со скриптом.
Все координаты — в единицах холста 16 x 9; правятся прямо здесь.
"""
import os
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle

plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["svg.fonttype"] = "none"  # текст в SVG остаётся текстом — редактируется вручную

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# --- палитра ----------------------------------------------------------------
BLUE_F, BLUE_E, BLUE_T = "#DBEAFE", "#2563EB", "#1E3A8A"      # управление
VIOL_F, VIOL_E, VIOL_T = "#EDE9FE", "#8B5CF6", "#5B21B6"      # сканеры
GREEN_F, GREEN_E, GREEN_T = "#D1FAE5", "#10B981", "#065F46"   # стенд
AMB_F, AMB_E, AMB_T = "#FEF3C7", "#D97706", "#92400E"         # MITM (герой)
GRAY_F, GRAY_E, GRAY_T = "#F3F4F6", "#9CA3AF", "#374151"      # внешние
INK = "#111827"
ARR = "#4B5563"

fig, ax = plt.subplots(figsize=(16, 9), dpi=170)
ax.set_xlim(0, 16)
ax.set_ylim(0, 9)
ax.axis("off")
fig.subplots_adjust(left=0, right=1, top=1, bottom=0)


def rbox(x, y, w, h, fc, ec, lw=1.6, ls="-", z=2, rounding=0.06):
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                                boxstyle=f"round,pad=0,rounding_size={rounding}",
                                facecolor=fc, edgecolor=ec, linewidth=lw,
                                linestyle=ls, zorder=z))


def arrow(p1, p2, color=ARR, lw=1.7, rad=0.0, ms=15, z=3):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=ms,
                                 color=color, linewidth=lw, shrinkA=2, shrinkB=2,
                                 connectionstyle=f"arc3,rad={rad}", zorder=z))


def label(x, y, s, size=9.5, color=INK, weight="normal", ha="center",
          va="center", z=4, ls_=1.25, halo=False):
    kw = {}
    if halo:  # белая подложка, чтобы линия не перечёркивала текст
        kw["bbox"] = dict(boxstyle="round,pad=0.18", facecolor="white",
                          edgecolor="none")
        z = 5
    ax.text(x, y, s, fontsize=size, color=color, fontweight=weight,
            ha=ha, va=va, zorder=z, linespacing=ls_, **kw)


# --- заголовок --------------------------------------------------------------
label(8, 8.72, "Архитектура платформы Agent Scanner", 21, INK, "bold")
label(8, 8.38, "8 типов проверок  ·  ноль изменений в коде агента  ·  "
      "оценка по фактическому трафику к LLM", 11.5, "#4B5563")

# --- зона A: управление (верхняя строка) ------------------------------------
# инженер-человечек
ax.add_patch(Circle((1.35, 7.97), 0.11, fill=False, lw=2.0, color=GRAY_T, zorder=3))
ax.plot([1.35, 1.35], [7.86, 7.60], lw=2.0, color=GRAY_T, zorder=3)
ax.plot([1.12, 1.58], [7.75, 7.75], lw=2.0, color=GRAY_T, zorder=3)
ax.plot([1.35, 1.16], [7.60, 7.37], lw=2.0, color=GRAY_T, zorder=3)
ax.plot([1.35, 1.54], [7.60, 7.37], lw=2.0, color=GRAY_T, zorder=3)
label(1.35, 7.16, "Инженер", 10.5, INK, "bold")

rbox(3.05, 7.35, 2.5, 0.75, BLUE_F, BLUE_E)
label(4.30, 7.90, "Веб-дашборд", 11.5, BLUE_T, "bold")
label(4.30, 7.56, "активы · сканы · отчёты", 9, "#374151")

rbox(6.65, 7.35, 2.8, 0.75, BLUE_F, BLUE_E)
label(8.05, 7.90, "Control API", 11.5, BLUE_T, "bold")
label(8.05, 7.56, "FastAPI · единый источник данных", 9, "#374151")

rbox(10.30, 7.35, 1.9, 0.75, "#EFF6FF", "#93C5FD")
label(11.25, 7.90, "PostgreSQL", 11, BLUE_T, "bold")
label(11.25, 7.56, "сканы · трафик · находки", 8.5, "#374151")

arrow((1.72, 7.72), (3.05, 7.72))
arrow((5.55, 7.72), (6.65, 7.72))
label(6.10, 7.86, "REST API", 9, "#6B7280")
arrow((9.45, 7.72), (10.30, 7.72))

# --- зона B: сканеры ---------------------------------------------------------
rbox(0.35, 2.75, 5.80, 3.60, "#FAFAFF", VIOL_E, lw=1.6, ls=(0, (6, 4)), z=1)
label(0.60, 6.08, "Сканеры · 8 типов проверок", 12.5, VIOL_T, "bold", ha="left")

rbox(0.55, 3.30, 2.65, 2.10, VIOL_F, VIOL_E, lw=1.3)
label(1.87, 5.16, "Динамические атаки", 11, VIOL_T, "bold")
label(0.75, 4.84, "•  DeepTeam · PyRIT\n"
                  "•  Инъекции в результаты\n     инструментов\n"
                  "•  Утечка системного промпта",
      9.8, "#3B2A6B", ha="left", va="top")

rbox(3.40, 3.30, 2.55, 2.10, VIOL_F, VIOL_E, lw=1.3)
label(4.67, 5.16, "Статический анализ", 11, VIOL_T, "bold")
label(3.60, 4.84, "•  Код агента — Promptfoo,\n     Semgrep\n"
                  "•  MCP-серверы — 7 движков\n"
                  "•  Agent Skills — 2 движка",
      9.8, "#3B2A6B", ha="left", va="top")

# --- зона C: испытательный стенд --------------------------------------------
rbox(6.55, 2.75, 9.10, 3.60, "#F7FDF9", GREEN_E, lw=1.6, ls=(0, (6, 4)), z=1)
label(6.80, 6.08, "Испытательный стенд · Kubernetes", 12.5, GREEN_T, "bold",
      ha="left")

rbox(6.85, 3.45, 3.0, 1.10, GREEN_F, GREEN_E, lw=1.6)
label(8.35, 4.30, "Launcher", 11.5, GREEN_T, "bold")
label(8.35, 3.92, "сборка образа (Kaniko),\nзапуск Pod'а агента", 9, "#374151")

rbox(10.55, 3.05, 4.80, 2.90, "white", "#9CA3AF", lw=1.4, ls=(0, (5, 4)), z=1)
label(10.72, 5.72, "Pod агента", 9.5, "#6B7280", ha="left")

rbox(10.85, 4.85, 4.2, 0.70, GREEN_F, GREEN_E, lw=1.6)
label(12.95, 5.36, "Тестируемый агент", 11.5, GREEN_T, "bold")
label(12.95, 5.04, "код и конфигурация не изменяются", 9, "#374151")

rbox(10.85, 3.45, 4.2, 0.80, AMB_F, AMB_E, lw=2.2)
label(12.95, 4.06, "MITM-прокси · сайдкар", 11.5, AMB_T, "bold")
label(12.95, 3.72, "перехват и переподписание TLS\nжурнал запросов — в Control API",
      8.8, "#78350F")

arrow((12.95, 4.85), (12.95, 4.25))
label(13.10, 4.55, "запросы к LLM", 9, "#6B7280", ha="left")

# --- внешние сервисы ---------------------------------------------------------
rbox(2.55, 1.35, 2.6, 0.80, GRAY_F, GRAY_E)
label(3.85, 1.93, "Git-репозитории", 11, GRAY_T, "bold")
label(3.85, 1.58, "код агентов и активов", 9, "#374151")

rbox(12.55, 1.35, 3.0, 0.80, GRAY_F, GRAY_E)
label(14.05, 1.93, "LLM-провайдер", 11, GRAY_T, "bold")
label(14.05, 1.58, "реальный, OpenAI-совместимый", 9, "#374151")

# --- стрелки -----------------------------------------------------------------
arrow((7.60, 7.35), (4.20, 6.37), rad=0.12)
label(5.30, 6.92, "запуск сканов", 9.5, "#374151", halo=True)

arrow((3.30, 6.37), (6.90, 7.33), rad=0.12)
label(4.30, 6.60, "логи и результаты", 9.5, "#374151", halo=True)

# журнал трафика: ортогональный маршрут из MITM-прокси вокруг стенда к Control API
ax.plot([15.05, 15.85], [3.85, 3.85], color="#B45309", lw=2.0, zorder=3,
        solid_capstyle="round")
ax.plot([15.85, 15.85], [3.85, 7.10], color="#B45309", lw=2.0, zorder=3,
        solid_capstyle="round")
arrow((15.85, 7.10), (9.35, 7.35), color="#B45309", lw=2.0)
label(12.75, 7.10, "журнал трафика — доказательства атак", 9.5, "#92400E",
      halo=True)

arrow((6.15, 5.20), (10.85, 5.20), color=VIOL_T, lw=2.2, ms=18)
label(8.50, 5.38, "атаки", 10.5, VIOL_T, "bold", halo=True)

arrow((9.90, 4.00), (10.55, 4.00), lw=1.7)
label(10.12, 4.17, "запускает", 8.5, "#6B7280")

arrow((3.85, 2.15), (7.05, 3.45), rad=0.15)
label(4.95, 2.66, "git clone", 9.5, "#374151", halo=True)

arrow((4.35, 2.95), (4.10, 2.17), lw=1.7)
label(4.98, 2.52, "клонирование", 9, "#374151", halo=True)

arrow((13.50, 3.45), (13.95, 2.17), color="#B45309", lw=2.0)
label(14.55, 2.78, "перехваченный\nтрафик", 9.5, "#92400E", halo=True)

# --- легенда -----------------------------------------------------------------
legend = [
    (0.50, BLUE_F, BLUE_E, "Управление"),
    (2.30, VIOL_F, VIOL_E, "Сканеры"),
    (3.90, GREEN_F, GREEN_E, "Стенд Kubernetes"),
    (6.30, AMB_F, AMB_E, "Перехват трафика (MITM)"),
    (8.90, GRAY_F, GRAY_E, "Внешние сервисы"),
]
for x, fc, ec, name in legend:
    rbox(x, 0.42, 0.45, 0.22, fc, ec, lw=1.2, rounding=0.04)
    label(x + 0.58, 0.53, name, 10, "#374151", ha="left")

fig.savefig(os.path.join(OUT_DIR, "architecture_agent_scanner.png"),
            facecolor="white")
fig.savefig(os.path.join(OUT_DIR, "architecture_agent_scanner.svg"),
            facecolor="white")
print("saved:", os.path.join(OUT_DIR, "architecture_agent_scanner.png"))
