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
) -> int:
    """Сохраняет артикул в БД, возвращает id записи."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO articles (user_id, article_code, marketplace, name, color, material)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (user_id, article_code, marketplace)
        DO UPDATE SET name = EXCLUDED.name, color = EXCLUDED.color,
                      material = EXCLUDED.material, parsed_at = NOW()
        RETURNING id
        """,
        user_id, article_code, marketplace, name, color, material,
    )
    return row["id"] if row else -1


async def save_reference(user_id: int, articul: str, file_id: str) -> int:
    """Сохраняет эталон (ссылку на изображение) в БД. Один эталон на артикул."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO article_references (user_id, articul, file_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id, articul)
        DO UPDATE SET file_id = EXCLUDED.file_id, created_at = NOW()
        RETURNING id
        """,
        user_id, articul, file_id,
    )
    return row["id"] if row else -1


async def get_reference(user_id: int, articul: str) -> asyncpg.Record | None:
    """Возвращает эталон для артикула. Один эталон — общий для фото и видео."""
    pool = await get_pool()
    return await pool.fetchrow(
        """
        SELECT * FROM article_references
        WHERE user_id = $1 AND articul = $2
        ORDER BY created_at DESC
        LIMIT 1
        """,
        user_id,
        articul,
    )


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
