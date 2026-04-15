Проблема: cb_close_alert_photo возвращал _P_COUNT (“Сколько фото?”), но алерт появлялся из состояния _P_WISH (“Нет пожеланий”). После закрытия пользователь попадал не туда — кнопки не работали.

Исправление: cb_close_alert_photo теперь возвращает _P_WISH — состояние откуда пришёл пользователь. После закрытия алерта кнопки “Нет пожеланий” и “Назад” работают.

cb_close_alert возвращает _REFERENCE_CONFIRM. Теперь:

_REFERENCE_GENERATING имеет alert_close → cb_close_alert → возвращает _REFERENCE_CONFIRM
_REFERENCE_CONFIRM имеет ref_create_yes → можно снова нажать “Создать эталон”
И _REFERENCE_GENERATING также имеет ref_create_yes для повторной попытки!
