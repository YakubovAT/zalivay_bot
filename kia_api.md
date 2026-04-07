# Kie.ai API Reference

Провайдер: https://api.kie.ai  
Документация: https://docs.kie.ai

---

## Аутентификация

Все запросы требуют заголовок:
```
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

---

## 1. Создание задачи

**POST** `/api/v1/jobs/createTask`

### Request body

```json
{
  "model": "gpt-image/1.5-image-to-image",
  "callBackUrl": "https://your-domain.com/callback",  // опционально
  "input": {
    "input_urls": ["https://example.com/image.jpg"],  // НЕ image_urls!
    "prompt": "...",
    "aspect_ratio": "1:1",  // "1:1" | "2:3" | "3:2"
    "quality": "medium"     // "medium" | "high"
  }
}
```

> ⚠️ Поле изображений называется `input_urls`, не `image_urls`.

### Response (успех)

```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "taskId": "task_gpt-image_1765968156336"
  }
}
```

### HTTP коды ответа

| Код | Описание |
|-----|----------|
| 200 | Задача создана, в `data.taskId` — идентификатор |
| 401 | Неверный API ключ |
| 402 | Недостаточно кредитов |
| 422 | Ошибка валидации запроса |
| 429 | Rate limit (макс. 20 запросов / 10 сек) |
| 500 | Внутренняя ошибка сервера |

---

## 2. Polling статуса задачи

**GET** `/api/v1/jobs/recordInfo?taskId={taskId}`

### Ответ пока задача обрабатывается (code 249)

```json
{
  "code": 249,
  "msg": "generating",
  "data": {
    "taskId": "task_gpt-image_1765968156336",
    "model": "gpt-image/1.5-image-to-image",
    "state": "generating"
  }
}
```

### Ответ когда задача готова (code 200)

```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "taskId": "task_gpt-image_1765968156336",
    "model": "gpt-image/1.5-image-to-image",
    "state": "success",
    "param": "{...}",
    "resultJson": "{\"resultUrls\":[\"https://cdn.kie.ai/result.jpg\"]}",
    "failCode": "",
    "failMsg": "",
    "costTime": 15000,
    "completeTime": 1698765432000,
    "createTime": 1698765400000,
    "updateTime": 1698765432000
  }
}
```

> ⚠️ `resultJson` — это **строка** (не объект!), её нужно `json.loads()`.  
> URL изображения: `json.loads(data["resultJson"])["resultUrls"][0]`

### Состояния задачи (`data.state`)

| state | Описание |
|-------|----------|
| `waiting` | В очереди, ожидает обработки |
| `queuing` | В очереди обработчика |
| `generating` | Генерируется |
| `success` | Завершено успешно |
| `fail` | Ошибка генерации |

### Логика кода в теле ответа

| code | Значение |
|------|----------|
| 249 | Задача ещё выполняется — продолжать polling |
| 200 | Запрос обработан — смотреть `state` |

### HTTP коды ответа

| Код | Описание |
|-----|----------|
| 200 | OK (проверять `code` в теле!) |
| 400 | Не передан или неверный `taskId` |
| 401 | Неверный API ключ |
| 404 | Задача не найдена |
| 429 | Rate limit |

---

## 3. T2T (Chat Completions)

**POST** `/gpt-5-2/v1/chat/completions`

OpenAI-совместимый формат.

```json
{
  "model": "gpt-5-2",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user",   "content": "..."}
  ]
}
```

---

## 4. Rate Limits

- Макс. **20 новых запросов / 10 сек**
- До **100+ задач** одновременно
- Превышение → HTTP 429, запрос не ставится в очередь

---

## 5. Хранение данных

- Сгенерированные файлы: **14 дней**
- Логи задач: **2 месяца**

---

## 6. Callback (вместо polling)

Опциональный `callBackUrl` в запросе — провайдер сам пришлёт уведомление о завершении. Альтернатива polling.
