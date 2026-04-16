"""
services/lifestyle_generator.py

Создание lifestyle-фото на модели через T2T AI + I2I AI.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Системный промпт для lifestyle-фото
# ---------------------------------------------------------------------------

LIFESTYLE_SYSTEM_PROMPT = """Ты — профессиональный промпт-инженер для image-to-image AI.
Твоя задача — сформировать точный промпт на английском языке
для создания lifestyle-фото товара на модели.
Отвечай ТОЛЬКО готовым промптом. Без пояснений и комментариев."""

LIFESTYLE_USER_TEMPLATE = (
    "У меня есть эталонное изображение товара со следующими характеристиками:\n"
    "- Название: {name}\n"
    "- Цвет: {color}\n"
    "- Материал: {material}\n\n"
    "Пользователь задал следующие критерии (некоторые могут быть пустыми):\n"
    "- Локация: {location}\n"
    "- Время года: {season}\n"
    "- Цвет волос модели: {hair_color}\n"
    "- Дополнительные пожелания: {extra}\n\n"
    "ПРАВИЛО ОБРАБОТКИ ПУСТЫХ ПОЛЕЙ (автоматический выбор):\n"
    "• Локация не указана → чистая студия с мягким светом или минималистичный городской фон\n"
    "• Сезон не указан → лёгкие ткани: весна/лето, плотные: осень/зима, иначе: нейтральный свет\n"
    "• Волосы не указаны → тёмно-русый/каштановый (нейтральный, не конкурирует с цветом товара)\n"
    "• Пожелания не указаны → стандарт fashion e-commerce: естественная поза, спокойное лицо, акцент на товаре\n\n"
    "На основе эталонного изображения и доступных критериев\n"
    "сформируй промпт на английском языке для image-to-image AI,\n"
    "который выполнит следующее:\n\n"
    "Промпт должен содержать задачу:\n"
    "— Использовать эталонное PNG как точный референс товара\n"
    "— Надеть [НАЗВАНИЕ] цвета [ЦВЕТ АРТ.] из [МАТЕРИАЛ АРТ.] на модель\n"
    "— Сохранить ВСЕ детали товара из эталона: цвет, текстуру,\n"
    "   форму, швы, принты, пропорции — без каких-либо изменений\n"
    "— Ссоздавать реалистичное lifestyle-фото в заданной\n"
    "   или автоматически подобранной локации\n"
    "— Модель должна органично вписываться в окружение\n\n"
    "Промпт должен содержать параметры съёмки\n"
    "(указанные пользователем или подобранные автоматически):\n"
    "— Локация и окружение\n"
    "— Сезон и освещение\n"
    "— Внешность модели\n"
    "— Стиль и настроение фото\n\n"
    "Промпт должен содержать требования к результату:\n"
    "— Товар полностью соответствует эталонному изображению\n"
    "— Естественная поза модели, соответствует стилю бренда\n"
    "— Максимальное разрешение, профессиональный e-commerce стандарт\n"
    "— Формат: JPG или PNG\n\n"
    "Промпт должен содержать критические ограничения:\n"
    "— Не изменять цвет, принт или форму товара из эталона\n"
    "— Товар должен выглядеть точно как на эталонном PNG\n"
    "— Не добавлять аксессуары или одежду, которых нет в задании\n"
    "— Ссоздавать и выдать финальное изображение\n\n"
    "Верни ТОЛЬКО готовый промпт на английском языке.\n"
    "Без пояснений, без комментариев, без markdown-разметки."
)


async def generate_lifestyle_prompt(
    session: aiohttp.ClientSession,
    name: str,
    color: str,
    material: str,
    location: str = "",
    season: str = "",
    hair_color: str = "",
    extra: str = "",
    api_key: str = "",
    api_base_url: str = "https://kie.ai",
    model: str = "gpt-5-2",
) -> str | None:
    """
    Создает промпт для lifestyle-фото через T2T AI.
    """
    user_prompt = LIFESTYLE_USER_TEMPLATE.format(
        name=name or "товар",
        color=color or "не указан",
        material=material or "не указан",
        location=location or "(авто)",
        season=season or "(авто)",
        hair_color=hair_color or "(авто)",
        extra=extra or "(авто)",
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": LIFESTYLE_SYSTEM_PROMPT},
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
                logger.error("Lifestyle T2T error: status=%s, body=%s", resp.status, text)
                return None

            data = await resp.json()
            prompt = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            logger.info("Lifestyle prompt generated (%d chars)", len(prompt))
            return prompt if prompt else None

    except Exception as e:
        logger.error("Lifestyle T2T request failed: %s", e)
        return None
