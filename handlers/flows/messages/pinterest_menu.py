"""
handlers/flows/messages/pinterest_menu.py

Тексты flow «📌 Пинтерест» (кнопка в главном меню).
Все шаблоны хранятся в БД (таблица prompt_templates) и редактируются через веб-панель.
"""

from services.prompt_store import get_template


async def msg_pinterest_menu_overview(
    photos_count: int,
    videos_count: int,
    watermarked_photos: int,
    watermarked_videos: int,
) -> str:
    template = await get_template("msg_pinterest_menu_overview")
    return template.format(
        photos_count=photos_count,
        videos_count=videos_count,
        watermarked_photos=watermarked_photos,
        watermarked_videos=watermarked_videos,
    )


async def msg_pinterest_menu_count(
    watermarked_photos: int,
    watermarked_videos: int,
    balance: int,
    cost_per_row: int,
) -> str:
    template = await get_template("msg_pinterest_menu_count")
    return template.format(
        watermarked_photos=watermarked_photos,
        watermarked_videos=watermarked_videos,
        balance=balance,
        cost_per_row=cost_per_row,
    )


async def msg_pinterest_menu_confirm(count: int, cost: int, balance: int, after: int) -> str:
    template = await get_template("msg_pinterest_menu_confirm")
    return template.format(count=count, cost=cost, balance=balance, after=after)


async def msg_pinterest_menu_insufficient(cost: int, balance: int) -> str:
    template = await get_template("msg_pinterest_menu_insufficient")
    return template.format(cost=cost, balance=balance)


async def msg_pinterest_menu_no_files() -> str:
    return await get_template("msg_pinterest_menu_no_files")


async def msg_pinterest_menu_generating(count: int) -> str:
    template = await get_template("msg_pinterest_menu_generating")
    return template.format(count=count)


async def msg_pinterest_menu_done(count: int, cost: int, balance: int) -> str:
    template = await get_template("msg_pinterest_menu_done")
    return template.format(count=count, cost=cost, balance=balance)


async def msg_pinterest_menu_distribution(count: int, articles_count: int) -> str:
    template = await get_template("msg_pinterest_menu_distribution")
    return template.format(count=count, articles_count=articles_count)


async def msg_pinterest_menu_article_select(articles_list: str) -> str:
    template = await get_template("msg_pinterest_menu_article_select")
    return template.format(articles_list=articles_list)
