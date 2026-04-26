import asyncpg
from config import DATABASE_URL

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL)
    return _pool


async def init_db():
    """Создаёт таблицы, если их нет."""
    pool = await get_pool()
    with open("database/schema.sql", "r", encoding="utf-8") as f:
        schema = f.read()
    async with pool.acquire() as conn:
        await conn.execute(schema)


async def ensure_user(user_id: int, username: str | None):
    """Регистрирует пользователя при первом обращении."""
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO users (user_id, username)
        VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username
        """,
        user_id,
        username,
    )


async def get_user(user_id: int) -> asyncpg.Record | None:
    pool = await get_pool()
    return await pool.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)


async def get_user_references(user_id: int) -> list[asyncpg.Record]:
    pool = await get_pool()
    return await pool.fetch(
        "SELECT * FROM article_references WHERE user_id = $1 ORDER BY created_at DESC",
        user_id,
    )


async def get_user_articles_with_refs(user_id: int) -> list[asyncpg.Record]:
    """Возвращает уникальные артикулы пользователя с количеством эталонов и названием."""
    pool = await get_pool()
    return await pool.fetch(
        """
        SELECT
            a.article_code,
            a.name,
            a.marketplace,
            COUNT(DISTINCT CASE WHEN ar.is_active = TRUE AND ar.deleted_at IS NULL THEN ar.id END) as ref_count
        FROM articles a
        INNER JOIN article_references ar
            ON ar.user_id = a.user_id AND ar.articul = a.article_code
        WHERE a.user_id = $1
          AND ar.is_active = TRUE
          AND ar.deleted_at IS NULL
        GROUP BY a.article_code, a.name, a.marketplace
        HAVING COUNT(DISTINCT CASE WHEN ar.is_active = TRUE AND ar.deleted_at IS NULL THEN ar.id END) > 0
        ORDER BY MAX(a.parsed_at) DESC
        """,
        user_id,
    )


async def get_user_stats(user_id: int) -> dict:
    """Возвращает статистику пользователя: эталоны, фото, видео, баланс."""
    pool = await get_pool()
    article_count = await pool.fetchval(
        "SELECT COUNT(DISTINCT article_code) FROM articles WHERE user_id = $1",
        user_id,
    )
    ref_count = await pool.fetchval(
        "SELECT COUNT(*) FROM article_references WHERE user_id = $1 AND is_active = TRUE AND deleted_at IS NULL",
        user_id,
    )
    photo_count = await pool.fetchval(
        """
        SELECT COUNT(*) FROM generation_tasks
        WHERE user_id = $1
          AND task_type = 'lifestyle_photo'
          AND status = 'completed'
        """,
        user_id,
    )
    video_count = 0  # TODO: видео создание не реализована

    row = await pool.fetchrow(
        "SELECT balance FROM users WHERE user_id = $1",
        user_id,
    )
    balance = row["balance"] if row else 0

    return {
        "articles": article_count or 0,
        "references": ref_count or 0,
        "photos": photo_count,
        "videos": video_count,
        "balance": balance,
    }


async def is_registered(user_id: int) -> bool:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT is_registered FROM users WHERE user_id = $1", user_id
    )
    return bool(row and row["is_registered"])


async def save_registration(user_id: int, ad_budget: str, articles_count: str):
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE users
        SET ad_budget = $2, articles_count = $3, is_registered = TRUE
        WHERE user_id = $1
        """,
        user_id,
        ad_budget,
        articles_count,
    )


async def log_user_action(user_id: int, username: str | None, action_type: str, content: str | None):
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO user_actions (user_id, username, action_type, content)
        VALUES ($1, $2, $3, $4)
        """,
        user_id,
        username,
        action_type,
        content,
    )


async def get_user_articles(user_id: int, article_code: str = None) -> list[asyncpg.Record]:
    """Возвращает артикулы пользователя. Если article_code — фильтрует по нему."""
    pool = await get_pool()
    if article_code:
        return await pool.fetch(
            "SELECT * FROM articles WHERE user_id = $1 AND article_code = $2 ORDER BY parsed_at DESC",
            user_id, article_code,
        )
    return await pool.fetch(
        "SELECT * FROM articles WHERE user_id = $1 ORDER BY parsed_at DESC",
        user_id,
    )


async def get_article_info(user_id: int, article_code: str) -> asyncpg.Record | None:
    """Возвращает информацию об одном артикуле (name, color, material и т.д.)."""
    pool = await get_pool()
    return await pool.fetchrow(
        "SELECT * FROM articles WHERE user_id = $1 AND article_code = $2 LIMIT 1",
        user_id, article_code,
    )


async def get_reference_product_name(user_id: int, article_code: str) -> str | None:
    """
    Возвращает product_name из последнего активного эталона артикула.

    Нужен для Pinterest board: после миграций имя товара может быть
    актуальнее в article_references, чем в articles.
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT product_name
        FROM article_references
        WHERE user_id = $1
          AND articul = $2
          AND is_active = TRUE
          AND deleted_at IS NULL
          AND product_name IS NOT NULL
          AND btrim(product_name) <> ''
        ORDER BY created_at DESC
        LIMIT 1
        """,
        user_id, article_code,
    )
    return row["product_name"] if row else None


async def delete_user(user_id: int):
    """Полностью удаляет пользователя и все его данные из БД (CASCADE)."""
    pool = await get_pool()
    await pool.execute("DELETE FROM users WHERE user_id = $1", user_id)


async def reset_registration(user_id: int):
    """Сбрасывает регистрацию пользователя для повторного прохождения онбординга."""
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE users
        SET ad_budget = NULL, articles_count = NULL, is_registered = FALSE
        WHERE user_id = $1
        """,
        user_id,
    )


async def save_article(
    user_id: int,
    article_code: str,
    marketplace: str,
    name: str,
    color: str,
    material: str,
    wb_images: list[str] | None = None,
) -> int:
    """Сохраняет артикул в БД, возвращает id записи.

    wb_images: список URL фото товара с WB (для I2I создания)
    """
    import json
    pool = await get_pool()
    wb_images_json = json.dumps(wb_images or [])
    row = await pool.fetchrow(
        """
        INSERT INTO articles (user_id, article_code, marketplace, name, color, material, wb_images)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (user_id, article_code, marketplace)
        DO UPDATE SET name = EXCLUDED.name, color = EXCLUDED.color,
                      material = EXCLUDED.material, wb_images = EXCLUDED.wb_images,
                      parsed_at = NOW()
        RETURNING id
        """,
        user_id, article_code, marketplace, name, color, material, wb_images_json,
    )
    return row["id"] if row else -1


async def save_reference(
    user_id: int,
    articul: str,
    file_id: str,
    file_path: str = "",
    reference_image_url: str = "",
    category: str = "",
    reference_prompt: str = "",
    reference_number: int = 1,
    product_name: str = "",
    product_color: str = "",
    product_material: str = "",
    product_description: str = "",
    source_photo_paths: str = "[]",
) -> int:
    """Сохраняет эталон в БД. Много эталонов на один артикул.

    reference_image_url: публичный URL эталона для I2I API
    category: классификация товара (верх/низ/обувь/головной убор)
    reference_prompt: промпт на английском для I2I создания
    product_description: краткое описание товара на английском (для создания фото/видео)
    reference_number: порядковый номер эталона для артикула
    product_name: название товара
    product_color: цвет товара
    product_material: материал товара
    source_photo_paths: JSON-массив путей к 3 исходным фото (для пересоздания)
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO article_references (user_id, articul, reference_number, file_id, file_path, reference_image_url, category, reference_prompt, product_description, product_name, product_color, product_material, source_photo_paths)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        RETURNING id
        """,
        user_id, articul, reference_number, file_id, file_path, reference_image_url, category, reference_prompt, product_description, product_name, product_color, product_material, source_photo_paths,
    )
    return row["id"] if row else -1


async def get_reference(user_id: int, articul: str, ref_number: int | None = None) -> asyncpg.Record | None:
    """Возвращает эталон для артикула.
    Если ref_number указан — конкретный, иначе — последний активный."""
    pool = await get_pool()
    if ref_number is not None:
        return await pool.fetchrow(
            """
            SELECT * FROM article_references
            WHERE user_id = $1 AND articul = $2 AND reference_number = $3
              AND is_active = TRUE AND deleted_at IS NULL
            """,
            user_id, articul, ref_number,
        )
    return await pool.fetchrow(
        """
        SELECT * FROM article_references
        WHERE user_id = $1 AND articul = $2 AND is_active = TRUE AND deleted_at IS NULL
        ORDER BY reference_number DESC
        LIMIT 1
        """,
        user_id,
        articul,
    )


async def get_active_references(user_id: int, articul: str) -> list[asyncpg.Record]:
    """Возвращает все активные эталоны для артикула (не в корзине)."""
    pool = await get_pool()
    return await pool.fetch(
        """
        SELECT * FROM article_references
        WHERE user_id = $1 AND articul = $2 AND is_active = TRUE AND deleted_at IS NULL
        ORDER BY reference_number
        """,
        user_id, articul,
    )


async def get_reference_count(user_id: int, articul: str) -> int:
    """Возвращает количество активных эталонов для артикула (не в корзине)."""
    pool = await get_pool()
    count = await pool.fetchval(
        "SELECT COUNT(*) FROM article_references WHERE user_id = $1 AND articul = $2 AND is_active = TRUE AND deleted_at IS NULL",
        user_id, articul,
    )
    return count or 0


async def soft_delete_reference(user_id: int, articul: str, ref_number: int) -> bool:
    """Мягкое удаление эталона (is_active = FALSE)."""
    pool = await get_pool()
    result = await pool.execute(
        """
        UPDATE article_references
        SET is_active = FALSE
        WHERE user_id = $1 AND articul = $2 AND reference_number = $3 AND is_active = TRUE
        """,
        user_id, articul, ref_number,
    )
    return "UPDATE 1" in result


async def deduct_balance(user_id: int, amount: int) -> int:
    """Списывает средства с баланса. Возвращает новый баланс."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        UPDATE users SET balance = balance - $2
        WHERE user_id = $1
        RETURNING balance
        """,
        user_id, amount,
    )
    return row["balance"] if row else -1


# ---------------------------------------------------------------------------
# Кэш маркетплейса
# ---------------------------------------------------------------------------

async def get_marketplace_cache(user_id: int, article: str) -> str | None:
    """Возвращает закэшированный маркетплейс ('WB' | 'OZON') или None."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT marketplace FROM marketplace_cache WHERE user_id = $1 AND article = $2",
        user_id,
        article,
    )
    return row["marketplace"] if row else None


async def save_marketplace_cache(user_id: int, article: str, marketplace: str) -> None:
    """Сохраняет результат валидации. Вызывается ТОЛЬКО при confidence=1.0."""
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO marketplace_cache (user_id, article, marketplace)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id, article)
        DO UPDATE SET marketplace = EXCLUDED.marketplace, cached_at = NOW()
        """,
        user_id,
        article,
        marketplace,
    )


# ---------------------------------------------------------------------------
# Очередь задач создания (фото / видео)
# ---------------------------------------------------------------------------

async def create_task(
    user_id: int,
    chat_id: int,
    task_type: str,
    articul: str,
    prompt: str,
) -> int:
    """Создаёт задачу создания. Возвращает id записи."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO generation_tasks (user_id, chat_id, task_type, articul, prompt)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        user_id, chat_id, task_type, articul, prompt,
    )
    return row["id"] if row else -1


async def get_pending_tasks(limit: int = 5) -> list[asyncpg.Record]:
    """Возвращает pending задачи, переводя их в processing (атомарно)."""
    pool = await get_pool()
    return await pool.fetch(
        """
        UPDATE generation_tasks
        SET status = 'processing', updated_at = NOW()
        WHERE id IN (
            SELECT id FROM generation_tasks
            WHERE status = 'pending'
              AND task_type IN ('photo', 'video')
            ORDER BY created_at
            LIMIT $1
        )
        RETURNING *
        """,
        limit,
    )


async def complete_task(task_id: int, result_url: str) -> None:
    """Помечает задачу как выполненную."""
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE generation_tasks
        SET status = 'completed', result_url = $2, updated_at = NOW()
        WHERE id = $1
        """,
        task_id, result_url,
    )


async def fail_task(task_id: int, error_msg: str) -> None:
    """Помечает задачу как неудачную."""
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE generation_tasks
        SET status = 'failed', error_msg = $2, updated_at = NOW()
        WHERE id = $1
        """,
        task_id, error_msg,
    )


async def fail_stuck_tasks(minutes: int = 10) -> int:
    """Переводит зависшие processing задачи обратно в pending."""
    pool = await get_pool()
    result = await pool.execute(
        """
        UPDATE generation_tasks
        SET status = 'pending', updated_at = NOW()
        WHERE status = 'processing'
          AND updated_at < NOW() - ($1 || ' minutes')::INTERVAL
        """,
        str(minutes),
    )
    return int(result.split()[-1])


# ---------------------------------------------------------------------------
# generation_jobs — группы задач (Вариант C)
# ---------------------------------------------------------------------------

async def create_generation_job(
    user_id: int,
    chat_id: int,
    article: str,
    ref_number: int,
    ref_image_url: str,
    wish: str | None,
    count: int,
    cost: int,
    screen_msg_id: int | None = None,
) -> int:
    """Создаёт группу создания. Возвращает job_id."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO generation_jobs
            (user_id, chat_id, article, ref_number, ref_image_url, wish, count, cost, screen_msg_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id
        """,
        user_id, chat_id, article, ref_number, ref_image_url, wish, count, cost, screen_msg_id,
    )
    return row["id"] if row else -1


async def create_job_task(
    job_id: int,
    user_id: int,
    chat_id: int,
    article: str,
    prompt: str,
) -> int:
    """Создаёт задачу внутри группы. Возвращает task_id."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO generation_tasks (job_id, user_id, chat_id, task_type, articul, prompt)
        VALUES ($1, $2, $3, 'lifestyle_photo', $4, $5)
        RETURNING id
        """,
        job_id, user_id, chat_id, article, prompt,
    )
    return row["id"] if row else -1


async def get_pending_job_tasks(limit: int = 10) -> list[asyncpg.Record]:
    """Берёт pending lifestyle_photo задачи (с job_id), атомарно переводит в processing."""
    pool = await get_pool()
    return await pool.fetch(
        """
        UPDATE generation_tasks
        SET status = 'processing', updated_at = NOW()
        WHERE id IN (
            SELECT id FROM generation_tasks
            WHERE status = 'pending'
              AND task_type = 'lifestyle_photo'
              AND job_id IS NOT NULL
            ORDER BY created_at
            LIMIT $1
        )
        RETURNING *
        """,
        limit,
    )


async def complete_job_task(task_id: int, result_url: str, file_path: str) -> None:
    """Помечает задачу группы как выполненную, сохраняет file_path."""
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE generation_tasks
        SET status = 'completed', result_url = $2, file_path = $3, updated_at = NOW()
        WHERE id = $1
        """,
        task_id, result_url, file_path,
    )


async def fail_job_task(task_id: int, error_msg: str) -> None:
    """Помечает задачу группы как неудачную."""
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE generation_tasks
        SET status = 'failed', error_msg = $2, updated_at = NOW()
        WHERE id = $1
        """,
        task_id, error_msg,
    )


async def get_job_status(job_id: int) -> dict:
    """Возвращает счётчики задач группы: total, completed, failed, pending."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT
            COUNT(*)                                      AS total,
            COUNT(*) FILTER (WHERE status = 'completed') AS completed,
            COUNT(*) FILTER (WHERE status = 'failed')    AS failed,
            COUNT(*) FILTER (WHERE status = 'pending'
                              OR   status = 'processing') AS in_progress
        FROM generation_tasks
        WHERE job_id = $1
        """,
        job_id,
    )
    return dict(row) if row else {"total": 0, "completed": 0, "failed": 0, "in_progress": 0}


async def get_job_info(job_id: int) -> asyncpg.Record | None:
    """Возвращает запись generation_jobs по id."""
    pool = await get_pool()
    return await pool.fetchrow(
        "SELECT * FROM generation_jobs WHERE id = $1",
        job_id,
    )


async def get_job_results(job_id: int) -> list[str]:
    """Возвращает file_path всех выполненных задач группы (по порядку)."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT file_path FROM generation_tasks
        WHERE job_id = $1 AND status = 'completed' AND file_path IS NOT NULL
        ORDER BY id
        """,
        job_id,
    )
    return [r["file_path"] for r in rows]


async def complete_generation_job(job_id: int) -> None:
    """Помечает группу как выполненную."""
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE generation_jobs SET status = 'done', updated_at = NOW()
        WHERE id = $1
        """,
        job_id,
    )


async def fail_generation_job(job_id: int) -> None:
    """Помечает группу как неудачную."""
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE generation_jobs SET status = 'failed', updated_at = NOW()
        WHERE id = $1
        """,
        job_id,
    )


async def fail_stuck_jobs(minutes: int = 15) -> int:
    """Сбрасывает зависшие processing задачи групп обратно в pending."""
    pool = await get_pool()
    result = await pool.execute(
        """
        UPDATE generation_tasks
        SET status = 'pending', updated_at = NOW()
        WHERE status = 'processing'
          AND task_type = 'lifestyle_photo'
          AND updated_at < NOW() - ($1 || ' minutes')::INTERVAL
        """,
        str(minutes),
    )
    return int(result.split()[-1])


# ---------------------------------------------------------------------------
# Video job — группы задач создания видео (lifestyle_video)
# ---------------------------------------------------------------------------

async def create_video_job_task(
    job_id: int,
    user_id: int,
    chat_id: int,
    article: str,
    prompt: str,
) -> int:
    """Создаёт задачу видео внутри группы. Возвращает task_id."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO generation_tasks (job_id, user_id, chat_id, task_type, articul, prompt)
        VALUES ($1, $2, $3, 'lifestyle_video', $4, $5)
        RETURNING id
        """,
        job_id, user_id, chat_id, article, prompt,
    )
    return row["id"] if row else -1


async def get_pending_video_job_tasks(limit: int = 5) -> list:
    """Берёт pending lifestyle_video задачи, атомарно переводит в processing."""
    pool = await get_pool()
    return await pool.fetch(
        """
        UPDATE generation_tasks
        SET status = 'processing', updated_at = NOW()
        WHERE id IN (
            SELECT id FROM generation_tasks
            WHERE status = 'pending'
              AND task_type = 'lifestyle_video'
              AND job_id IS NOT NULL
            ORDER BY created_at
            LIMIT $1
        )
        RETURNING *
        """,
        limit,
    )


async def fail_stuck_video_jobs(minutes: int = 30) -> int:
    """Сбрасывает зависшие processing lifestyle_video задачи обратно в pending."""
    pool = await get_pool()
    result = await pool.execute(
        """
        UPDATE generation_tasks
        SET status = 'pending', updated_at = NOW()
        WHERE status = 'processing'
          AND task_type = 'lifestyle_video'
          AND updated_at < NOW() - ($1 || ' minutes')::INTERVAL
        """,
        str(minutes),
    )
    return int(result.split()[-1])


# ---------------------------------------------------------------------------
# media_files — реестр сгенерированных медиафайлов
# ---------------------------------------------------------------------------

async def register_media_file(
    user_id: int,
    article_code: str,
    task_id: int | None,
    file_path: str,
    result_url: str | None,
    file_type: str,
) -> int:
    """Регистрирует медиафайл в реестре. Возвращает id записи."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO media_files (user_id, article_code, task_id, file_path, result_url, file_type)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        user_id, article_code, task_id, file_path, result_url, file_type,
    )
    return row["id"] if row else -1


async def get_unexported_media_files(user_id: int, article_code: str) -> list[asyncpg.Record]:
    """Возвращает все файлы артикула (без фильтра по экспорту)."""
    pool = await get_pool()
    return await pool.fetch(
        """
        SELECT * FROM media_files
        WHERE user_id = $1 AND article_code = $2
        ORDER BY created_at
        """,
        user_id, article_code,
    )


async def get_all_unexported_media_files(user_id: int) -> list[asyncpg.Record]:
    """Возвращает watermark-файлы пользователя ещё не попавшие в Pinterest CSV."""
    pool = await get_pool()
    return await pool.fetch(
        """
        SELECT * FROM media_files
        WHERE user_id = $1
          AND is_watermark = TRUE
          AND pinterest_export_count = 0
        ORDER BY created_at
        """,
        user_id,
    )


async def mark_pinterest_exported(file_ids: list[int]) -> None:
    """Увеличивает счётчик экспортов для файлов и фиксирует дату последнего."""
    if not file_ids:
        return
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE media_files
        SET pinterest_export_count = pinterest_export_count + 1,
            pinterest_exported_at  = NOW()
        WHERE id = ANY($1::int[])
        """,
        file_ids,
    )


# ---------------------------------------------------------------------------
# pinterest_settings — настройки Pinterest
# ---------------------------------------------------------------------------

async def get_pinterest_settings(user_id: int, article_code: str) -> dict:
    """Возвращает настройки Pinterest с fallback: артикул → пользователь → пусто."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM pinterest_settings
        WHERE user_id = $1 AND (article_code = $2 OR article_code IS NULL)
        ORDER BY article_code NULLS LAST
        """,
        user_id, article_code,
    )
    result: dict = {"board": None, "link_template": None, "hashtags": []}
    for row in reversed(rows):  # user-level первый, article переопределяет
        if row["board"]:
            result["board"] = row["board"]
        if row["link_template"]:
            result["link_template"] = row["link_template"]
        if row["hashtags"]:
            result["hashtags"] = list(row["hashtags"])
    return result


async def get_unwatermarked_photos(user_id: int) -> list[asyncpg.Record]:
    """Возвращает оригинальные фото пользователя без watermark-копии."""
    pool = await get_pool()
    return await pool.fetch(
        """
        SELECT * FROM media_files
        WHERE user_id = $1
          AND file_type = 'photo'
          AND file_path IS NOT NULL
          AND is_watermark = FALSE
          AND watermark_count = 0
          AND article_code != '00000'
        ORDER BY created_at
        """,
        user_id,
    )


async def create_watermarked_file(
    parent_id: int,
    user_id: int,
    article_code: str,
    file_path: str,
    file_type: str,
) -> int:
    """Создаёт запись watermark-файла и инкрементирует счётчик на оригинале."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO media_files (user_id, article_code, file_path, file_type, is_watermark, parent_id)
        VALUES ($1, $2, $3, $4, TRUE, $5)
        RETURNING id
        """,
        user_id, article_code, file_path, file_type, parent_id,
    )
    await pool.execute(
        "UPDATE media_files SET watermark_count = watermark_count + 1 WHERE id = $1",
        parent_id,
    )
    return row["id"] if row else -1


async def get_media_file_by_id(media_file_id: int) -> asyncpg.Record | None:
    """Возвращает запись media_files по id."""
    pool = await get_pool()
    return await pool.fetchrow(
        "SELECT * FROM media_files WHERE id = $1",
        media_file_id,
    )


async def save_pinterest_settings(
    user_id: int,
    article_code: str | None,
    board: str | None = None,
    link_template: str | None = None,
    hashtags: list[str] | None = None,
) -> None:
    """Сохраняет настройки Pinterest. article_code=None → уровень пользователя."""
    pool = await get_pool()
    if article_code is not None:
        await pool.execute(
            """
            INSERT INTO pinterest_settings (user_id, article_code, board, link_template, hashtags)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id, article_code) WHERE article_code IS NOT NULL
            DO UPDATE SET board = EXCLUDED.board,
                          link_template = EXCLUDED.link_template,
                          hashtags = EXCLUDED.hashtags
            """,
            user_id, article_code, board, link_template, hashtags,
        )
    else:
        await pool.execute(
            """
            INSERT INTO pinterest_settings (user_id, article_code, board, link_template, hashtags)
            VALUES ($1, NULL, $2, $3, $4)
            ON CONFLICT (user_id) WHERE article_code IS NULL
            DO UPDATE SET board = EXCLUDED.board,
                          link_template = EXCLUDED.link_template,
                          hashtags = EXCLUDED.hashtags
            """,
            user_id, board, link_template, hashtags,
        )
