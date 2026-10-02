# Шпаргалка по серверу

Все команды выполняются под **root**, если не сказано иначе.
Бот живёт в `/home/bot/queue-bot`, служба называется `queue-bot`.

## Работает ли бот

```bash
systemctl status queue-bot           # active (running) — работает; там же видна память
journalctl -u queue-bot -f           # логи в реальном времени, выход — Ctrl+C
journalctl -u queue-bot -n 100       # последние 100 строк логов
journalctl -u queue-bot --since "1 hour ago"   # логи за последний час
```

## Управление службой

```bash
systemctl restart queue-bot   # перезапустить (после обновления кода или правки .env)
systemctl stop queue-bot      # остановить
systemctl start queue-bot     # запустить
systemctl disable queue-bot   # не запускать после перезагрузки сервера
systemctl enable queue-bot    # снова запускать после перезагрузки
```

## Обновление через git

**На своём компьютере**, в папке проекта:

```bash
git add .
git commit -m "что поменял"
git push
```

**На сервере**:

```bash
su - bot -c "cd ~/queue-bot && git pull && ~/.local/bin/uv sync"
systemctl restart queue-bot
systemctl status queue-bot    # убедиться, что поднялся
```

`uv sync` нужен, только если менялись библиотеки (`pyproject.toml`, `uv.lock`), но лишним не будет.

### Откат, если новая версия сломалась

```bash
su - bot
cd ~/queue-bot
git log --oneline          # список версий, слева — короткий хеш
git checkout ХЕШ           # вернуться на рабочую версию
exit
systemctl restart queue-bot
```

Чтобы потом вернуться на последнюю версию: `git checkout main`, затем `git pull`.

## Настройки (.env)

```bash
nano /home/bot/queue-bot/.env    # сохранить: Ctrl+O, Enter; выйти: Ctrl+X
systemctl restart queue-bot      # без перезапуска изменения не применятся
```

## База с очередью (queue.db)

**Резервная копия на сервере:**

```bash
systemctl stop queue-bot
cp /home/bot/queue-bot/queue.db /home/bot/queue-backup-$(date +%F).db
systemctl start queue-bot
```

**Скачать копию на свой компьютер** (PowerShell на компьютере):

```bash
scp root@IP_СЕРВЕРА:/home/bot/queue-bot/queue.db .
```

**Если обновление поменяло структуру таблиц**, бот при запуске упадёт с ошибкой про колонки. Тогда сделайте копию, как выше, удалите `queue.db` и перезапустите бота — он создаст базу заново. Очередь при этом обнулится.

## Работа с базой через sqlite3

Один раз установить клиент: `apt install -y sqlite3`

### Как зайти и выйти

```bash
sqlite3 /home/bot/queue-bot/queue.db
```

Приглашение сменится на `sqlite>` — теперь вводится SQL, а не команды Linux.

```sql
.headers on       -- показывать названия колонок
.mode column      -- выводить таблицей
.tables           -- список таблиц
.schema queue     -- структура таблицы
.quit             -- выйти обратно в терминал
```

Каждый SQL-запрос заканчивается `;`. Если видно `...>` — забыли `;`, допишите и нажмите Enter.

Запрос можно выполнить и без входа, одной строкой:

```bash
sqlite3 /home/bot/queue-bot/queue.db "SELECT * FROM queue;"
```

### Таблицы

| Таблица | Что хранит |
|---|---|
| `users` | Telegram ID (`tg_id`) и имя (`full_name`) |
| `queue` | текущие очереди: `tg_id`, `subject`, `topic` (0 — без темы), `work_num`, `called` (1 — сейчас сдаёт), `joined_ts` (когда записался, unix-время) |

Очереди на закончившиеся пары бот очищает сам, раз в 30 секунд. Если в старой базе осталась таблица `submissions`, она больше не используется — её можно удалить: `DROP TABLE submissions;`

Предметы пишутся маленькими буквами: `'мбп'`, `'оирткпс'`, `'тестирование'`, `'рбд'`, `'котлин'`.

### Посмотреть

```sql
-- очередь по предмету в том порядке, как её видит бот
SELECT u.full_name, q.topic, q.work_num, q.called
FROM queue q JOIN users u USING(tg_id)
WHERE q.subject = 'рбд'
ORDER BY q.called DESC, q.topic, q.work_num, q.id;

-- когда кто записался (по московскому времени)
SELECT u.full_name, q.subject, datetime(q.joined_ts, 'unixepoch', '+3 hours') AS joined
FROM queue q JOIN users u USING(tg_id)
ORDER BY q.joined_ts;

-- найти tg_id человека по имени
SELECT tg_id, full_name FROM users WHERE full_name LIKE '%Иван%';
```

### Изменить

**Перед изменениями — бэкап** (см. выше), а для массовых правок лучше остановить бота: `systemctl stop queue-bot`, потом `systemctl start queue-bot`.

```sql
-- очистить ВСЕ очереди
DELETE FROM queue;

-- очистить очередь одного предмета
DELETE FROM queue WHERE subject = 'мбп';

-- убрать одного человека из очереди
DELETE FROM queue WHERE tg_id = 123456789 AND subject = 'рбд';

-- снять отметку «сейчас сдаёт», не удаляя из очереди
UPDATE queue SET called = 0 WHERE subject = 'рбд';

```

⚠️ Подтверждения нет: `DELETE` без `WHERE` удаляет всю таблицу сразу.

## Нагрузка на сервер

```bash
free -h     # память
df -h /     # место на диске
htop        # процессы в реальном времени (если нет: apt install -y htop), выход — q
```

## Частые проблемы

| Что видно | Что значит | Что делать |
|---|---|---|
| `Conflict: terminated by other getUpdates request` | бот с этим токеном запущен где-то ещё | остановить второй экземпляр, например у себя на компьютере |
| `Unauthorized` | неверный токен | проверить `BOT_TOKEN` в `.env` |
| `uv: command not found` | терминал не видит uv | писать полный путь `/home/bot/.local/bin/uv` или выполнить `source ~/.local/bin/env` |
| `KeyError: 'BOT_TOKEN'` | нет `.env` или в нём нет токена | создать `.env` из `.env.example` |
| служба `failed` | бот упал при запуске | смотреть `journalctl -u queue-bot -n 50` |
| бот не отвечает, служба `active` | проблема со связью до Telegram | `curl -s https://api.telegram.org` — должен прийти ответ |
