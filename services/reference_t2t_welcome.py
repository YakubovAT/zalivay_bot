"""
services/reference_t2t_welcome.py

Создание категории и описания товара для велком флоу через Text AI.

Вход:
  - name, color, material — данные товара из wb_parser_welcome
Выход:
  - dict {"category": "верх|низ|обувь|головной убор|комплект", "description": "описание"} или None
"""

from __future__ import annotations

import json
import logging

import aiohttp

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — профессиональный промпт-инженер для Pinterest.

Твои задачи:
1. Определить категорию товара: верх / низ / обувь / головной убор / комплект
2. Создать шаблон описания для Pinterest с переменными (max 300 символов)

Категория «комплект» — для цельных изделий: платье, сарафан, комбинезон, ромпер, туника, спортивный костюм, пижама, халат, боди, купальник.

Отвечай СТРОГО в следующем формате (без markdown):
CATEGORY: [верх|низ|обувь|головной убор|комплект]
DESCRIPTION: {STYLE} [текст с переменными {TREND}, {OCCASION}, {DETAILS}, {AESTHETIC}] [хештеги]"""

USER_TEMPLATE = (
    "Характеристики товара:\n"
    "- Название: {name}\n"
    "- Цвет: {color}\n"
    "- Материал: {material}\n\n"
    "1. Определи категорию: верх / низ / обувь / головной убор / комплект\n\n"
    "2. Создай описание для Pinterest (max 300 символов):\n"
    "— Используй переменные: {{STYLE}}, {{TREND}}, {{OCCASION}}, {{DETAILS}}, {{AESTHETIC}}\n"
    "— SEO-оптимизированный текст\n"
    "— Добавь релевантные хештеги в конец\n\n"
    "Ответ СТРОГО в формате:\n"
    "CATEGORY: [верх|низ|обувь|головной убор|комплект]\n"
    "DESCRIPTION: {{STYLE}} [текст] {{TREND}} [текст] {{OCCASION}} [текст] {{DETAILS}} [текст] {{AESTHETIC}} [текст] [хештеги]"
)

VALID_CATEGORIES = {"верх", "низ", "обувь", "головной убор", "комплект"}


def _parse_response(raw: str) -> dict | None:
    """Парсит ответ T2T с категорией и описанием."""
    category = ""
    description_lines = []
    current_section = None

    for line in raw.splitlines():
        stripped = line.strip()
        upper_stripped = stripped.upper()

        if upper_stripped.startswith("CATEGORY:"):
            category = stripped[len("CATEGORY:"):].strip().lower()
            current_section = None
        elif upper_stripped.startswith("DESCRIPTION:") or upper_stripped.startswith("DESC:"):
            description_lines.append(stripped.split(":", 1)[1].strip())
            current_section = "description"
        elif current_section == "description":
            description_lines.append(line)

    description = "\n".join(description_lines).strip()
    description = description.strip('"').strip()

    if not category or not description:
        logger.error("T2T welcome parse failed: category=%r, desc_len=%d",
                      category, len(description))
        return None

    if category not in VALID_CATEGORIES:
        logger.error("T2T welcome вернул неизвестную категорию %r", category)
        return None

    return {
        "category": category,
        "description": description,
    }


async def generate_welcome_description(
    session: aiohttp.ClientSession,
    name: str,
    color: str,
    material: str,
    api_key: str,
    api_base_url: str = "https://kie.ai",
    model: str = "gpt-5-2",
) -> dict | None:
    """
    Создает категорию и описание товара для велком флоу.

    Returns:
        {
            "category": "верх|низ|обувь|головной убор|комплект",
            "description": "описание с переменными {STYLE}, {TREND} и т.д."
        }
        или None при ошибке.
    """
    user_prompt = USER_TEMPLATE.format(
        name=name or "товар",
        color=color or "не указан",
        material=material or "не указан",
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }

    logger.info("T2T welcome request | model=%s | name=%r | color=%r | material=%r",
                model, name, color, material)

    try:
        url = f"{api_base_url}/{model}/v1/chat/completions"
        logger.info("T2T welcome request | url=%s", url)

        async with session.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            raw_text = await resp.text()
            logger.info("T2T welcome response | status=%s | body_len=%d",
                        resp.status, len(raw_text))

            if resp.status != 200:
                logger.error("T2T welcome error: status=%s, body=%s", resp.status, raw_text[:500])
                return None

            try:
                data = json.loads(raw_text)
            except Exception as e:
                logger.error("T2T welcome JSON parse error: %s", e)
                return None

            raw = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            logger.info("T2T welcome raw response: %s", raw[:200])

            result = _parse_response(raw)
            if result:
                logger.info("T2T welcome parsed: category=%s, desc_len=%d",
                            result["category"], len(result["description"]))
            return result

    except Exception as e:
        logger.error("T2T welcome request failed: %s", e)
        return None
