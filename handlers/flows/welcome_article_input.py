"""
handlers/flows/welcome_article_input.py

Обработчик велком флоу: ввод артикула → парсинг → генерация → результаты.

Состояния:
  _WELCOME_ARTICLE_INPUT = 6  — экран ввода артикула
  _WELCOME_LOADING = 7        — загрузка + генерация
  _WELCOME_RESULTS = 8        — результаты + 4 фото + CSV
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re

import aiohttp
from telegram import Update
from telegram.ext import ContextTypes

from config import (
    AI_API_KEY, AI_API_BASE, AI_MODEL,
    I2I_API_KEY, I2I_API_BASE,
)
from database import (
    save_article, save_reference, mark_welcome_completed, get_user,
    get_user_stats,
)
from handlers.flows.flow_helpers import send_screen
from handlers.keyboards import kb_welcome_article_input, kb_welcome_csv_ready
from handlers.flows.messages.common import msg_profile
from handlers.keyboards import kb_main_menu
from services.prompt_store import get_template, get_banner, get_list
from services.wb_parser_welcome import get_product_info
from services.reference_t2t_welcome import generate_welcome_description
from services.reference_i2i_welcome import generate_reference_image, generate_4_photos
from services.pinterest_csv_generator import generate_pinterest_csv
from services.media_storage import ensure_user_media_dirs
from services.image_prompt_generator import generate_image_prompt

logger = logging.getLogger(__name__)

_WELCOME_ARTICLE_INPUT = 5


def _generate_reference_prompt(product_name: str, color: str, material: str) -> str:
    """Генерирует детальный prompt для I2I эталона товара."""
    return f"""Проанализировать фото и найти {product_name} цвета {color} из {material}.
Выделить ТОЛЬКО {product_name}, удалить модель, фон, аксессуары, текст.
Сохранить 3D-форму, пропорции, текстуру ткани, складки, швы, узоры.
Создать PNG с прозрачным фоном (RGBA), высокое разрешение.
Фотореалистичность, студийное качество, чистые края.
По центру как на невидимом манекене, полностью виден от верха до низа.
Не менять цвета, не добавлять детали."""


async def show_article_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает экран ввода артикула (шаг 1ф)."""
    user = update.effective_user

    text = await get_template("msg_welcome_step_1f")
    banner_name = await get_banner("msg_welcome_step_1f")

    await send_screen(
        context.bot,
        chat_id=user.id,
        text=text,
        keyboard=kb_welcome_article_input(),
        banner_path=f"assets/{banner_name}",
    )

    context.user_data["welcome_step"] = "1f"
    return _WELCOME_ARTICLE_INPUT


async def handle_article_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает текст пользователя (артикул или ссылка)."""
    user = update.effective_user
    text = update.message.text.strip()

    # Извлекаем артикул из текста (6-9 цифр)
    match = re.search(r'\b(\d{6,9})\b', text)
    if not match:
        # Ошибка: неправильный артикул
        error_text = "❌ Не удалось распознать артикул введите правильный"
        msg = await context.bot.send_message(chat_id=user.id, text=error_text)
        # Удалить через 5 сек
        asyncio.create_task(_delete_message_after(context.bot, user.id, msg.message_id, 5))
        return _WELCOME_ARTICLE_INPUT

    article_code = match.group(1)
    logger.info("Welcome article input: user=%s article=%s", user.id, article_code)

    # Сохраняем артикул в context для использования при генерации
    context.user_data["welcome_article"] = article_code

    # Показываем экран загрузки
    return await show_loading(update, context, article_code)


async def show_loading(update: Update, context: ContextTypes.DEFAULT_TYPE, article_code: str) -> int:
    """Показывает экран загрузки и начинает процесс генерации."""
    from telegram.ext import ConversationHandler

    user = update.effective_user

    # Показываем экран загрузки
    text = await get_template("msg_loading_welcome")
    msg = await context.bot.send_message(chat_id=user.id, text=text)
    context.user_data["loading_msg_id"] = msg.message_id

    # Запускаем длительную операцию парсинга + генерации в фоне
    asyncio.create_task(
        _process_welcome_generation(
            context.bot,
            user.id,
            article_code,
            context.user_data,
        )
    )

    # Выходим из ConversationHandler — длительная операция будет в фоне
    return ConversationHandler.END


async def _process_welcome_generation(bot, user_id: int, article_code: str, user_data: dict):
    """Длительная операция: парсинг → T2T → I2I → CSV → результаты."""
    try:
        logger.info("Welcome generation started | user=%s | article=%s", user_id, article_code)

        # 1. ПАРСИНГ ТОВАРА
        logger.info("Welcome: parsing article %s", article_code)
        product = await get_product_info(article_code)
        if not product or not product.get("name"):
            await bot.send_message(
                chat_id=user_id,
                text="❌ Артикул не найден. Проверьте и попробуйте снова."
            )
            return

        name = product.get("name", "")
        color = product.get("colors", [""])[0] if product.get("colors") else ""
        material = product.get("material", "")
        wb_images = product.get("images", [])

        logger.info("Welcome: parsed | name=%s | color=%s | images=%d", name, color, len(wb_images))

        # Сохраняем в БД таблицу articles
        article_id = await save_article(
            user_id=user_id,
            article_code=article_code,
            marketplace="WB",
            name=name,
            color=color,
            material=material,
            wb_images=wb_images,
        )
        logger.info("Welcome: saved article | id=%d", article_id)

        # Создаём папку для медиа
        media_root = ensure_user_media_dirs(user_id)
        logger.info("Welcome: media_root=%s", media_root)

        # Скачиваем изображения и продолжаем с aiohttp сессией
        async with aiohttp.ClientSession() as session:
            # 2. T2T: ГЕНЕРАЦИЯ ОПИСАНИЯ И КАТЕГОРИИ
            logger.info("Welcome: calling T2T")
            t2t_result = await generate_welcome_description(
                session=session,
                name=name,
                color=color,
                material=material,
                api_key=AI_API_KEY,
                api_base_url=AI_API_BASE,
                model=AI_MODEL,
            )
            if not t2t_result:
                await bot.send_message(
                    chat_id=user_id,
                    text="❌ Что-то пошло не так. Попробуйте позже."
                )
                return

            category = t2t_result.get("category")
            description = t2t_result.get("description")
            logger.info("Welcome: T2T result | category=%s | desc_len=%d", category, len(description))

            # 3. I2I: СОЗДАНИЕ ЭТАЛОНА
            logger.info("Welcome: calling I2I for reference")
            reference_prompt = _generate_reference_prompt(name, color, material)
            ref_image_url = await generate_reference_image(
                session=session,
                api_base=I2I_API_BASE,
                api_key=I2I_API_KEY,
                image_urls=wb_images[:4],  # первые 4 фото
                prompt=reference_prompt,
            )
            if not ref_image_url:
                await bot.send_message(
                    chat_id=user_id,
                    text="❌ Что-то пошло не так. Попробуйте позже."
                )
                return

            logger.info("Welcome: I2I reference done | url=%s", ref_image_url)

            # Сохраняем эталон в БД
            await save_reference(
                user_id=user_id,
                articul=article_code,
                file_id="",  # для велком флоу не сохраняем file_id
                file_path="",
                reference_image_url=ref_image_url,
                category=category,
                reference_prompt="",
                reference_number=1,
                product_name=name,
                product_color=color,
                product_material=material,
                product_description=description,
                source_photo_paths=json.dumps(wb_images[:3]),
            )
            logger.info("Welcome: saved reference")

            # 4. I2I: ГЕНЕРАЦИЯ 4 ФОТО
            # Генерируем 4 lifestyle-промта для категории товара
            logger.info("Welcome: generating 4 lifestyle prompts for category=%s", category)
            lifestyle_prompts = []
            for i in range(4):
                prompt = await generate_image_prompt(category=category)
                if prompt:
                    lifestyle_prompts.append(prompt)
                else:
                    logger.error("Welcome: failed to generate prompt #%d", i + 1)

            if len(lifestyle_prompts) < 4:
                await bot.send_message(
                    chat_id=user_id,
                    text="❌ Что-то пошло не так. Попробуйте позже."
                )
                return

            logger.info("Welcome: generated %d lifestyle prompts", len(lifestyle_prompts))

            # Функция generate_4_photos сама объединит 4 промта в сетку
            logger.info("Welcome: calling I2I for 4 photos grid")
            photos_url = await generate_4_photos(
                session=session,
                api_base=I2I_API_BASE,
                api_key=I2I_API_KEY,
                image_urls=wb_images[:4],
                prompts=lifestyle_prompts,
            )
            if not photos_url:
                await bot.send_message(
                    chat_id=user_id,
                    text="❌ Что-то пошло не так. Попробуйте позже."
                )
                return

            logger.info("Welcome: I2I 4photos done | url=%s", photos_url)

            # 5. ГЕНЕРАЦИЯ CSV
            logger.info("Welcome: generating CSV")
            csv_result = await generate_pinterest_csv(
                user_id=user_id,
                rows_count=4,
                article_code_filter=article_code,
            )
            csv_content = csv_result.get("content", "")
            logger.info("Welcome: CSV generated | len=%d", len(csv_content))

        # 6. ПОКАЗЫВАЕМ РЕЗУЛЬТАТЫ
        logger.info("Welcome: showing results to user")
        await show_results(
            bot=bot,
            user_id=user_id,
            article_code=article_code,
            csv_content=csv_content,
        )

        # 7. ЧЕРЕЗ 60 СЕК → ПЕРЕХОД В МЕНЮ
        logger.info("Welcome: waiting 60 sec before transition to menu")
        await asyncio.sleep(60)

        logger.info("Welcome: marking as completed | user=%s", user_id)
        await mark_welcome_completed(user_id)

        # Показываем меню
        user_obj = await get_user(user_id)
        if user_obj:
            stats = await get_user_stats(user_id)
            text = await msg_profile(user_id, user_obj.get("username") or "User", stats)

            await send_screen(
                bot,
                chat_id=user_id,
                text=text,
                keyboard=kb_main_menu(),
                parse_mode="MarkdownV2",
            )

        logger.info("Welcome: completed successfully | user=%s", user_id)

    except Exception as e:
        logger.error("Welcome generation error: %s", e, exc_info=True)
        await bot.send_message(
            chat_id=user_id,
            text="❌ Что-то пошло не так. Попробуйте позже."
        )


async def show_results(bot, user_id: int, article_code: str, csv_content: str):
    """Отправляет результаты: CSV."""
    try:
        # Отправляем CSV файл
        csv_file = io.BytesIO(csv_content.encode('utf-8-sig'))
        csv_file.name = f"pinterest_pins_{article_code}.csv"

        await bot.send_document(
            chat_id=user_id,
            document=csv_file,
            caption=(
                "✅ Готово! Вот ваш CSV для Pinterest.\n\n"
                "Как загружать?\n"
                "[инструкция будет добавлена]\n\n"
                "Хотите загрузить через Pinterest-креаторов? Свяжитесь с нами 👤"
            ),
            reply_markup=kb_welcome_csv_ready(),
        )

    except Exception as e:
        logger.error("Error showing welcome results: %s", e)


async def cb_welcome_article_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Кнопка 'Назад' на экране ввода артикула → шаг 1е."""
    from handlers.flows.onboarding import _show_welcome_step

    query = update.callback_query
    await query.answer()
    return await _show_welcome_step(update, context, "1e", message_id=query.message.message_id)


async def cb_welcome_csv_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Кнопка 'В меню' на экране результатов → главное меню (обработка вне ConversationHandler)."""
    query = update.callback_query
    await query.answer()
    # Эта кнопка может быть обработана вне ConversationHandler
    return


async def cb_welcome_photo_close(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Кнопка 'Закрыть' на сообщении с фото → удаляет сообщение."""
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception as e:
        logger.debug("Failed to delete message: %s", e)
    return


async def _delete_message_after(bot, chat_id: int, message_id: int, delay: int):
    """Удаляет сообщение через delay секунд."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.debug("Failed to delete message: %s", e)
