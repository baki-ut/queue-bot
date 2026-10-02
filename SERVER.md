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
