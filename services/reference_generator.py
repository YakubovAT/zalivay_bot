"""
services/reference_generator.py

Генерация промпта для эталона через Text AI.

Вход:
  - name, color, material — данные товара из wb_parser
Выход:
  - Готовый промпт на английском для I2I AI генерации
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Системный промпт для эталона
# ---------------------------------------------------------------------------

REFERENCE_SYSTEM_PROMPT = """Ты — профессиональный промпт-инженер для image-to-image AI.
Твоя задача — сформировать точный промпт на английском языке
для обработки фотографии одежды в image-to-image системе.
Отвечай ТОЛЬКО готовым промптом. Без пояснений и комментариев."""

REFERENCE_USER_TEMPLATE = (
    "У меня есть фотографии товара со следующими характеристиками:\n"
    "- Название: {name}\n"
    "- Цвет: {color}\n"
    "- Материал: {material}\n\n"
    "На основе этих характеристик сформируй промпт на английском языке\n"
    "для image-to-image AI, который выполнит следующее:\n\n"
    "Промпт должен содержать задачу:\n"
    "— Проанализировать фотографии и найти [НАЗВАНИЕ] из [МАТЕРИАЛ АРТ.]\n"
    "   цвета [ЦВЕТ АРТ.], проверить соответствие цвета на фото\n"
    "— Выделить ТОЛЬКО [НАЗВАНИЕ] со всех изображений\n"
    "— Полностью удалить тело модели\n"
    "— Удалить фон, аксессуары, текст и все остальные объекты\n"
    "— Сохранить естественную 3D-форму изделия с точными пропорциями\n"
    "— Сохранить все детали ткани: текстуру, складки, швы,\n"
    "   строчку, узоры, принты\n"
    "— Сохранить точные цвета и освещение\n\n"
    "Промпт должен содержать требования к результату:\n"
    "— Создать новое PNG-изображение с выделенным [НАЗВАНИЕ]\n"
    "— Прозрачный фон (RGBA)\n"
    "— Максимальное разрешение, профессиональный e-commerce стандарт\n"
    "— По центру, как на невидимом манекене\n"
    "— Сохранить оригинальные пропорции из исходных фотографий\n"
    "— Чистые края, без ореолов, без артефактов\n"
    "— Подходит для каталога одежды и видео-анимации\n"
    "— Форма изделия сохранена для 3D-реконструкции\n\n"
    "Промпт должен содержать критические ограничения:\n"
    "— Вывести ТОЛЬКО [НАЗВАНИЕ] — ничего больше\n"
    "— Не добавлять, не выдумывать и не изменять детали изделия\n"
    "— Не менять цвета или узоры\n"
    "— Сгенерировать и выдать финальное изображение\n\n"
    "Верни ТОЛЬКО готовый промпт на английском языке.\n"
    "Без пояснений, без комментариев, без markdown-разметки."
    "{additional_requirements}"
)


async def generate_reference_prompt(
    session: aiohttp.ClientSession,
    name: str,
    color: str,
    material: str,
    api_key: str,
    api_base_url: str = "https://kie.ai",
    model: str = "gpt-5-2",
    additional_requirements: str = "",
) -> str | None:
    """
    Генерирует промпт для эталона через Text AI.

    additional_requirements: строка с пожеланиями пользователя на русском.
        Будет добавлена в конец промпта как «Additional requirements: ...»

    Returns: промпт на английском или None при ошибке.
    """
    additional = (
        f"\n\nДополнительные пожелания: {additional_requirements}"
        if additional_requirements else ""
    )

    user_prompt = REFERENCE_USER_TEMPLATE.format(
        name=name or "товар",
        color=color or "не указан",
        material=material or "не указан",
        additional_requirements=additional,
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": REFERENCE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }

    try:
        async with session.post(
            f"{api_base_url}/{model}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error(
                    "Text AI error: status=%s, body=%s", resp.status, text
                )
                return None

            data = await resp.json()
            prompt = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            logger.info("Reference prompt generated (%d chars)", len(prompt))
            return prompt if prompt else None

    except Exception as e:
        logger.error("Text AI request failed: %s", e)
        return None
