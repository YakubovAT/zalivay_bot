import aiohttp

MAX_BASKET = 50
MAX_IMAGES = 30


def _vol_part(nmid: int) -> tuple[int, int]:
    return nmid // 100000, nmid // 1000


def _img_url(basket: int, vol: int, part: int, nmid: int, i: int) -> str:
    return (
        f"https://basket-{basket:02d}.wbbasket.ru"
        f"/vol{vol}/part{part}/{nmid}/images/big/{i}.webp"
    )


def _card_url(basket: int, vol: int, part: int, nmid: int) -> str:
    return (
        f"https://basket-{basket:02d}.wbbasket.ru"
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

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        basket = await _find_basket(session, nmid, vol, part)
        if basket is None:
            return {}

        card = await _fetch_card(session, basket, vol, part, nmid)
        images = await _collect_images(session, nmid, vol, part, basket)

    options = card.get("options", [])

    colors = [v for opt in options
              if opt.get("name") == "Цвет"
              for v in opt.get("variable_values", [])]

    material_values = [v for opt in options
                       if opt.get("name") in ("Состав", "Материал")
                       for v in opt.get("variable_values", [])]
    material = ", ".join(material_values) if material_values else ""

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
) -> int | None:
    """Перебирает корзины по порядку, возвращает первую где есть 1.webp."""
    for basket in range(1, MAX_BASKET + 1):
        url = _img_url(basket, vol, part, nmid, 1)
        try:
            async with session.head(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status == 200:
                    return basket
        except Exception:
            continue
    return None


async def _fetch_card(
    session: aiohttp.ClientSession, basket: int, vol: int, part: int, nmid: int
) -> dict:
    """Загружает info/ru/card.json из корзины."""
    url = _card_url(basket, vol, part, nmid)
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 200:
                return await r.json(content_type=None)
    except Exception:
        pass
    return {}


async def _collect_images(
    session: aiohttp.ClientSession, nmid: int, vol: int, part: int, basket: int
) -> list[str]:
    """Собирает URL всех фото из найденной корзины пока не 404."""
    urls = []
    for i in range(1, MAX_IMAGES + 1):
        url = _img_url(basket, vol, part, nmid, i)
        try:
            async with session.head(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status == 200:
                    urls.append(url)
                else:
                    break
        except Exception:
            break
    return urls
