import logging

import aiohttp

logger = logging.getLogger(__name__)

MAX_BASKET = 50
MAX_IMAGES = 30
WB_DOMAINS = ["wbcontent.net"]


def _vol_part(nmid: int) -> tuple[int, int]:
    return nmid // 100000, nmid // 1000


def _img_url(domain: str, basket: int, vol: int, part: int, nmid: int, i: int) -> str:
    return (
        f"https://basket-{basket:02d}.{domain}"
        f"/vol{vol}/part{part}/{nmid}/images/big/{i}.webp"
    )


def _card_url(domain: str, basket: int, vol: int, part: int, nmid: int) -> str:
    return (
        f"https://basket-{basket:02d}.{domain}"
        f"/vol{vol}/part{part}/{nmid}/info/ru/card.json"
    )


async def get_product_info(articul: str) -> dict:
    """
    Возвращает:
      {
        "name":        "Джинсы со стразами широкие.",
        "brand":       "RILAVIE",
        "colors":      ["голубой", "серебристо-синий", ...],
        "description": "...",
        "images":      ["https://basket-21.wbbasket.ru/.../1.webp", ...]
      }
    """
    nmid = int(articul)
    vol, part = _vol_part(nmid)
    logger.info("WB parser: артикул=%s vol=%s part=%s", articul, vol, part)

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        result = await _find_basket(session, nmid, vol, part)
        if result is None:
            logger.warning("WB parser: корзина не найдена для артикула %s", articul)
            return {}

        basket, domain = result
        logger.info("WB parser: артикул=%s найден в корзине %02d domain=%s", articul, basket, domain)
        card = await _fetch_card(session, domain, basket, vol, part, nmid)
        images = await _collect_images(session, nmid, vol, part, basket, domain)
        logger.info("WB parser: артикул=%s карточка=%s фото=%d", articul, bool(card), len(images))

    options = card.get("options", [])
    logger.debug("WB parser options: %s", options)

    colors = [v for opt in options
              if opt.get("name") == "Цвет"
              for v in opt.get("variable_values", [])]

    # Состав — ищем по нескольким вариантам названия поля
    material_values = []
    for opt in options:
        opt_name = opt.get("name", "")
        if opt_name in ("Состав", "Материал"):
            # Может быть в 'value' (строка) или 'variable_values' (массив)
            val = opt.get("value", "")
            if val:
                material_values = [val]
            else:
                material_values = opt.get("variable_values", [])
            break

    material = ", ".join(material_values) if material_values else ""

    logger.info("WB parser: material=%r from_options=%s", material, bool(material_values))

    return {
        "name":        card.get("imt_name"),
        "brand":       card.get("selling", {}).get("brand_name"),
        "colors":      colors or card.get("nm_colors_names", "").split(", "),
        "material":    material,
        "description": card.get("description"),
        "images":      images,
    }


async def _find_basket(
    session: aiohttp.ClientSession, nmid: int, vol: int, part: int
) -> tuple[int, str] | None:
    """Перебирает корзины и домены, возвращает (basket, domain) где есть 1.webp."""
    for basket in range(1, MAX_BASKET + 1):
        for domain in WB_DOMAINS:
            url = _img_url(domain, basket, vol, part, nmid, 1)
            try:
                async with session.head(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                    logger.debug("WB basket-%02d %s: status=%s", basket, domain, r.status)
                    if r.status == 200:
                        return basket, domain
            except Exception as e:
                logger.debug("WB basket-%02d %s: ошибка %s", basket, domain, e)
                continue
    return None


async def _fetch_card(
    session: aiohttp.ClientSession, domain: str, basket: int, vol: int, part: int, nmid: int
) -> dict:
    """Загружает info/ru/card.json из корзины."""
    url = _card_url(domain, basket, vol, part, nmid)
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            logger.debug("WB card.json: status=%s url=%s", r.status, url)
            if r.status == 200:
                return await r.json(content_type=None)
            logger.warning("WB card.json: неожиданный статус %s для %s", r.status, nmid)
    except Exception as e:
        logger.warning("WB card.json: ошибка для %s: %s", nmid, e)
    return {}


async def _collect_images(
    session: aiohttp.ClientSession, nmid: int, vol: int, part: int, basket: int, domain: str
) -> list[str]:
    """Собирает URL всех фото из найденной корзины пока не 404."""
    urls = []
    for i in range(1, MAX_IMAGES + 1):
        url = _img_url(domain, basket, vol, part, nmid, i)
        try:
            async with session.head(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status == 200:
                    urls.append(url)
                else:
                    break
        except Exception:
            break
    return urls
