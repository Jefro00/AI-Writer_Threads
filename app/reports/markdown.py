"""Markdown renderer."""
from __future__ import annotations


def render_markdown(title: str, facts: dict, narrative: dict) -> str:
    lines = [f"# {title}", "", f"_Сформировано: {facts.get('total_posts', 0)} публикаций_", ""]

    lines += ["## 1. Обзор", ""]
    for key, label in [
        ("total_posts", "Публикаций"), ("total_authors", "Авторов"),
        ("total_links", "Ссылок"), ("total_funnels", "Воронок"),
    ]:
        lines.append(f"- {label}: {facts.get(key, 0)}")
    lines.append("")

    lines += ["## 2. Распределение", ""]
    for name, data in [("Ниши", facts.get("niches", {})), ("Языки", facts.get("languages", {})), ("Механики", facts.get("mechanics", {}))]:
        lines.append(f"### {name}")
        for k, v in sorted(data.items(), key=lambda x: -x[1]):
            lines.append(f"- {k}: {v}")
        lines.append("")

    lines += ["## 3. Закономерности", ""]
    patterns = narrative.get("patterns") or []
    lines += [f"- {p}" for p in patterns] or ["- Данных недостаточно."]
    lines.append("")

    lines += ["## 4. Рекомендации", ""]
    lines += [f"- {r}" for r in (narrative.get("recommendations") or [])] or ["- Нет данных."]
    lines.append("")

    lines += ["## 5. Ограничения", ""]
    lines += [f"- {l}" for l in (narrative.get("limitations") or facts.get("limitations") or [])]
    lines.append("")
    lines += ["## 6. Примеры", ""]
    for ex in narrative.get("examples") or []:
        if isinstance(ex, dict):
            lines.append(f"- Post #{ex.get('post_id')}: {ex.get('why')}")
    lines.append("")
    lines.append(f"Уверенность AI: {narrative.get('confidence', 0)}")
    return "\n".join(lines)
