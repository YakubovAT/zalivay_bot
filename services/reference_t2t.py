"""
services/reference_t2t.py

Генерация промпта для эталона + классификация категории товара через Text AI.

Вход:
  - name, color, material — данные товара из wb_parser
Выход:
  - dict {"category": "верх|низ|обувь|головной убор", "prompt": "EN prompt"} или None
"""

from __future__ import annotations

import json
import logging

import aiohttp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Системный промпт
# ---------------------------------------------------------------------------

REFERENCE_SYSTEM_PROMPT = """Ты — профессиональный промпт-инженер для image-to-image AI.

Твои задачи:
1. Определить категорию товара одежды из списка: верх / низ / обувь / головной убор
2. Сформировать промпт на английском языке для обработки фотографии одежды в image-to-image системе (изоляция товара, удаление фона/модели)
3. Составить краткое описание товара на английском языке (для генерации фото/видео в будущем)

Отвечай СТРОГО в следующем формате (без пояснений, без markdown):
CATEGORY: [верх|низ|обувь|головной убор]
PROMPT_I2I: [промт для I2I — изоляция товара]
DESCRIPTION: [краткое описание товара на английском]"""

REFERENCE_USER_TEMPLATE = (
    "У меня есть фотографии товара со следующими характеристиками:\n"
    "- Название: {name}\n"
    "- Цвет: {color}\n"
    "- Материал: {material}\n\n"
    "На основе этих характеристик:\n\n"
    "1. Определи категорию: верх (рубашка, футболка, блузка, свитер, куртка и т.д.) / "
    "низ (юбка, брюки, шорты, джинсы и т.д.) / "
    "обувь (кроссовки, туфли, сапоги и т.д.) / "
    "головной убор (шапка, кепка, шляпа и т.д.)\n\n"
    "2. Сформируй PROMPT_I2I на английском языке для image-to-image AI, который выполнит следующее:\n\n"
    "Задача промпта:\n"
    "— Проанализировать фотографии и найти {name} из {material}\n"
    "   цвета {color}, проверить соответствие цвета на фото\n"
    "— Выделить ТОЛЬКО {name} со всех изображений\n"
    "— Полностью удалить тело модели\n"
    "— Удалить фон, аксессуары, текст и все остальные объекты\n"
    "— Сохранить естественную 3D-форму изделия с точными пропорциями\n"
    "— Сохранить все детали ткани: текстуру, складки, швы, строчку, узоры, принты\n"
    "— Сохранить точные цвета и освещение\n\n"
    "Требования к результату:\n"
    "— Создать новое PNG-изображение с выделенным {name}\n"
    "— Прозрачный фон (RGBA)\n"
    "— Максимальное разрешение, профессиональная фотореалистичная фотосъёмка\n"
    "— Фотореалистичность: как профессиональная студийная фотография товара\n"
    "— Реалистичная текстура ткани, естественные складки и тени\n"
    "— По центру, как на невидимом манекене\n"
    "— Чистые края, без ореолов, без артефактов\n"
    "— Подходит для каталога одежды и видео-анимации\n"
    "— КРИТИЧНО: показать изделие ПОЛНОСТЬЮ от верха до низа, БЕЗ обрезки краёв\n"
    "— Весь предмет должен быть полностью виден в кадре с отступами сверху и снизу\n\n"
    "Критические ограничения:\n"
    "— Вывести ТОЛЬКО {name} — ничего больше\n"
    "— Не добавлять, не выдумывать и не изменять детали изделия\n"
    "— Не менять цвета или узоры\n\n"
    "3. Составь DESCRIPTION — краткое описание товара на английском языке:\n"
    "— Тип товара + цвет + материал\n"
    "— Ключевые детали (воланы, кружево, карманы и т.д.)\n"
    "— Для какого сезона/случая подходит\n"
    "{additional_requirements}\n\n"
    "Ответ СТРОГО в формате:\n"
    "CATEGORY: [верх|низ|обувь|головной убор]\n"
    "PROMPT_I2I: [промт для I2I]\n"
    "DESCRIPTION: [краткое описание товара на английском]"
)

# Допустимые категории
VALID_CATEGORIES = {"верх", "низ", "обувь", "головной убор"}


def _parse_response(raw: str) -> dict | None:
    """
    Парсит ответ T2T вида:
      CATEGORY: низ
      PROMPT_I2I: Extract only the...
      DESCRIPTION: White summer skirt shorts...

    Возвращает {"category": "низ", "prompt_i2i": "...", "description": "..."} или None.
    """
    category = ""
    prompt_i2i_lines = []
    description_lines = []
    current_section = None

    for line in raw.splitlines():
        stripped = line.strip()
        upper_stripped = stripped.upper()

        if upper_stripped.startswith("CATEGORY:"):
            category = stripped[len("CATEGORY:"):].strip().lower()
            current_section = None
        elif upper_stripped.startswith("PROMPT_I2I:") or upper_stripped.startswith("PROMPT:"):
            prompt_i2i_lines.append(stripped.split(":", 1)[1].strip())
            current_section = "prompt"
        elif upper_stripped.startswith("DESCRIPTION:") or upper_stripped.startswith("DESC:"):
            description_lines.append(stripped.split(":", 1)[1].strip())
            current_section = "description"
        elif current_section == "prompt":
            prompt_i2i_lines.append(line)
        elif current_section == "description":
            description_lines.append(line)

    prompt_i2i = "\n".join(prompt_i2i_lines).strip()
    description = "\n".join(description_lines).strip()

    # Убираем кавычки если есть
    prompt_i2i = prompt_i2i.strip('"').strip()
    description = description.strip('"').strip()

    if not category or not prompt_i2i:
        logger.error("T2T parse failed: category=%r, prompt_len=%d, desc_len=%d",
                      category, len(prompt_i2i), len(description))
        return None

    # Нормализуем категорию
    if category not in VALID_CATEGORIES:
        logger.warning("Unknown category %r, defaulting to 'верх'", category)
        category = "верх"

    return {
        "category": category,
        "prompt_i2i": prompt_i2i,
        "description": description,
    }


async def generate_reference_prompt(
    session: aiohttp.ClientSession,
    name: str,
    color: str,
    material: str,
    api_key: str,
    api_base_url: str = "https://kie.ai",
    model: str = "gpt-5-2",
    additional_requirements: str = "",
) -> dict | None:
    """
    Генерирует промпт для эталона + категорию + описание товара через T2T AI.

    Returns:
        {
            "category": "верх|низ|обувь|головной убор",
            "prompt_i2i": "EN prompt for I2I isolation",
            "description": "EN description of the product"
        }
        или None при ошибке.
    """
    additional = (
        f"\nДополнительные пожелания: {additional_requirements}"
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

    logger.info("T2T request payload | model=%s | name=%r | color=%r | material=%r",
                model, name, color, material)
    logger.debug("T2T request messages: %s", json.dumps(payload["messages"], ensure_ascii=False))

    try:
        # Kie.ai T2T endpoint: {api_base_url}/{model}/v1/chat/completions
        # Пример: https://kie.ai/gpt-5-2/v1/chat/completions
        url = f"{api_base_url}/{model}/v1/chat/completions"
        logger.info("T2T request | model=%s | url=%s", model, url)

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
            logger.info("T2T response | status=%s | content_type=%s | body_len=%d",
                        resp.status, resp.content_type, len(raw_text))

            if resp.status != 200:
                logger.error("T2T error: status=%s, body=%s", resp.status, raw_text[:500])
                return None

            try:
                data = json.loads(raw_text)
            except Exception as e:
                logger.error("T2T JSON parse error: %s | body=%s", e, raw_text[:500])
                return None
            logger.info("T2T full JSON response: %s", json.dumps(data, ensure_ascii=False)[:500])
            raw = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            logger.info("T2T raw response (%d chars): %s", len(raw), raw[:200])

            result = _parse_response(raw)
            if result:
                logger.info("T2T parsed: category=%s, prompt_len=%d, desc_len=%d",
                            result["category"], len(result["prompt_i2i"]), len(result["description"]))
            return result

    except Exception as e:
        logger.error("T2T request failed: %s", e)
        return None
