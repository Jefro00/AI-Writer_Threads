# AI Writer — подготовка к проверке Meta (v0.3.3)

**Всё необходимое на стороне кода подготовлено.** Приложение нельзя опубликовать в личном кабинете Meta или Render автоматически без доступа владельца к GitHub, Render и Meta. Адрес сервиса появится только после его создания в Render.

## 1. Что теперь есть в приложении

| Раздел | Публичный путь | Требует пароля? |
|---|---|---|
| Описание AI Writer (для проверяющего) | `/meta` | Нет |
| Политика конфиденциальности RU + EN | `/privacy` | Нет |
| Пользовательское соглашение RU + EN | `/terms` | Нет |
| Инструкции удаления данных RU + EN | `/data-deletion` | Нет |
| Значок 1024×1024 PNG | `/static/ai-writer-icon.png` | Нет |
| Проверка доступности сервиса | `/healthz` | Нет |
| Правила индексации для Meta | `/robots.txt` | Нет |
| Панель генерации | `/` | Да, HTTP Basic |
| Research | `/research` | Да, HTTP Basic |
| OAuth callback | `/auth/threads/callback` | Нет, но требует корректного `state` |

Контакт оператора в документах: **jefrocrypto@gmail.com**. Это адрес из твоего скриншота настроек приложения Meta. Перед отправкой на проверку убедись, что ты действительно принимаешь на него запросы.

## 2. Публикация на Render бесплатно

1. Распакуй ZIP в новую директорию; ничего из старого `.env` в репозиторий не загружай. Репозиторий GitHub может быть приватным.
2. Создай проект на [Render](https://dashboard.render.com/) → **New → Web Service** → подключи репозиторий → **Docker** → **Free**. Можно также создать Blueprint из `render.yaml`.
3. **Environment:** задай `ADMIN_USERNAME`, уникальный `ADMIN_PASSWORD`, `GEMINI_API_KEY` или `OPENROUTER_API_KEY`. Пока не обязательно заполнять доступ Threads.
4. Для долговременной работы добавь `DATABASE_URL` с постоянным PostgreSQL. Без него приложение работает на временной SQLite, **данные исчезнут после redeploy/restart**. Free Render засыпает после 15 минут бездействия, поэтому фоновая публикация и планировщик по умолчанию выключены.
5. Нажми **Deploy**. После успешного запуска Render даст URL вида `https://jefrocrypto-threads-engine.onrender.com` (реальный URL может отличаться).
6. В Render Environment задай `PUBLIC_BASE_URL=https://<реальный-адрес>.onrender.com`. Перезапусти сервис при необходимости.

Проверь из приватного окна браузера (не вводя пароль):

- `https://<твой-сервис>.onrender.com/privacy`
- `https://<твой-сервис>.onrender.com/terms`
- `https://<твой-сервис>.onrender.com/data-deletion`
- `https://<твой-сервис>.onrender.com/meta`
- `https://<твой-сервис>.onrender.com/static/ai-writer-icon.png`
- `https://<твой-сервис>.onrender.com/healthz`

Или выполни команду **из своего локального проекта**, после развёртывания:

```powershell
py tools/meta_preflight.py --url https://<твой-сервис>.onrender.com
```

В отличие от приватного API, все эти пути должны отвечать **HTTP 200 без логина**.

## 3. Meta Developers → Settings / Основное

Тебе не нужно создавать новое Meta-приложение, используй **AI Writer** из скриншота.

| Поле Meta | Что указать |
|---|---|
| Отображаемое название | `AI Writer` |
| Значок приложения | `app/static/ai-writer-icon.png` (1024×1024 PNG, <5 MB) |
| URL Политики конфиденциальности | `https://<твой-сервис>.onrender.com/privacy` |
| URL Пользовательского соглашения | `https://<твой-сервис>.onrender.com/terms` |
| Удаление данных пользователей | Выбери **URL инструкций для удаления данных**, вставь `https://<твой-сервис>.onrender.com/data-deletion` |
| Контактный email | `jefrocrypto@gmail.com` |
| Категория | `Productivity / Продуктивность` (если доступна), иначе `Business / Бизнес` |
| Домены приложений | `<твой-сервис>.onrender.com` **без** `https://` (если Meta запрашивает) |
| Namespace | По возможности оставь пустым; не требуется для этой интеграции |

> **Важно:** все три адреса должны реально открываться публично, иначе Meta снова выдаст «Currently ineligible for submission». Копировать пример с `<...>` в Meta нельзя. Тексты политики и условий — готовые черновики, но владелец обязан убедиться, что они соответствуют фактической обработке данных и применимым требованиям права.

## 4. Threads OAuth / Redirect URLs

В Meta → **Use cases → Access the Threads API → Settings** (название меню может отличаться) укажи в **Valid OAuth Redirect URIs**:

```text
https://<твой-сервис>.onrender.com/auth/threads/callback
```

URL должен **буквально совпадать** с переменной Render `THREADS_REDIRECT_URI`. В Render Environment установи:

```env
THREADS_APP_ID=<ID именно Threads из Meta, НЕ общий App ID>
THREADS_APP_SECRET=<Threads secret, скрыть из Git>
THREADS_REDIRECT_URI=https://<твой-сервис>.onrender.com/auth/threads/callback
THREADS_OAUTH_STATE=  # необязательно; только для старого локального сценария
THREADS_REQUESTED_SCOPES=threads_basic,threads_content_publish
THREADS_OWN_USERNAME=web3sergeich
THREADS_KEYWORD_SEARCH_ENABLED=false
THREADS_PROFILE_DISCOVERY_ENABLED=false
```

**Рекомендуемый способ на Render (v0.3.3):**

1. Убедись, что `THREADS_APP_ID` — именно Threads App ID, а не общий Meta App ID; также заполнены `THREADS_APP_SECRET` и `THREADS_REDIRECT_URI`.
2. Meta → Threads API → Valid OAuth Redirect URIs: `https://ai-writer-threads.onrender.com/auth/threads/callback` (или твой действительный домен).
3. Открой **в том же браузере**, где будешь подтверждать Meta: `https://ai-writer-threads.onrender.com/auth/threads/start` и введи `ADMIN_USERNAME`/`ADMIN_PASSWORD` своего сервиса.
4. Приложение автоматически создаст уникальный `state` (10 минут), временную Secure/HttpOnly cookie и переадресует на Threads. Вручную открывать `/auth/threads/callback` нельзя.
5. После согласия Meta переадресует обратно на callback. Он проверит `state` и покажет одноразовый `code`. Не публикуй этот код и не показывай его в скриншотах.
6. На своём компьютере с теми же `THREADS_APP_ID`, `THREADS_APP_SECRET` и `THREADS_REDIRECT_URI` в локальном `.env` запусти:

```powershell
py tools/refresh_threads_token.py exchange "<CODE>"
```

7. Скрипт положит `THREADS_ACCESS_TOKEN` в локальный `.env`. Скопируй **только значение** этой переменной в Render → Environment → Save, deploy. Сам `.env` в GitHub не загружай.

> Если при открытии `/auth/threads/callback` видишь «OAuth state не совпадает», первым делом начни **новую** авторизацию через `/auth/threads/start`. Не открывай callback вручную; при входе из другого браузера или спустя 10 минут cookie не совпадёт. При изменении Render Environment нужно выполнить Save, deploy. В новых версиях `THREADS_OAUTH_STATE` для браузерного пути не требуется.

**Старый вариант через локальный URL (для обратной совместимости):** если используешь команду `py tools/refresh_threads_token.py url`, задай **одно и то же** `THREADS_OAUTH_STATE` локально и в Render; генерируется командой `py -c "import secrets; print(secrets.token_urlsafe(32))"`. Этот вариант не рекомендуется, потому что легко ошибиться при переносе значения.

Не запрашивай расширенные разрешения Threads до одобрения Meta. По умолчанию используются только `threads_basic,threads_content_publish`.

После отдельного App Review и выдачи прав поиска чужих постов обнови `THREADS_REQUESTED_SCOPES`, пройди OAuth снова и выставь `THREADS_KEYWORD_SEARCH_ENABLED=true` только при подтверждённом Advanced Access для `threads_keyword_search`; аналогично `threads_profile_discovery` для мониторинга других аккаунтов. До этого Research не сможет полноценно искать чужие посты.

## 5. Готовый сценарий для Meta App Review

**English (copy into review notes, adapt to actual permissions requested):**

> AI Writer is a privately operated content research and drafting tool for Threads. The app connects an authorized Threads profile, creates AI-assisted draft posts, and allows the operator to review and explicitly approve each post before publishing through the Threads API. It can also display the operator's permitted Threads data and, if separately approved, public content for research. It does not automate posting without operator approval by default. The public Privacy Policy, Terms, and Data Deletion Instructions are accessible without login. The operator can be contacted at jefrocrypto@gmail.com.

Для демонстрации сделай короткую **запись экрана** (Meta может запросить её для каждой заявленной функции): авторизация Threads → Writer → генерация → ручное одобрение → публикация (если есть рабочие разрешения) → проверка результата в Threads. Для `threads_keyword_search` нужна **отдельная** демонстрация именно поиска публичных публикаций **чужих авторов** с одобренным доступом, а не собственной выдачи. Никогда не показывай ключи, токены, приватные данные или секретные параметры в записи. Проверяющим Meta могут потребоваться тестовые учётные данные для панели, которые следует передавать только через официальный защищённый интерфейс App Review.

## 6. Заявки на удаление

Выбран режим **Data Deletion Instructions URL**, поэтому отдельный callback Meta для автоматического удаления не нужен. В Приложении опубликована контактная инструкция, а не ложная кнопка «Удалить». Оператор должен **реально принимать и обрабатывать обращения** с email, проверять право заявителя на данные и удалять релевантные записи/токены из используемой базы и окружения. Отзыв авторизации в Meta не удаляет ранее сохранённые локальные данные автоматически. Пока нет отдельного механизма удаления по аккаунту, процесс ручной: запрос → проверка → резервная копия/поиск данных → удаление → подтверждение заявителю. Учитывай и резервные копии, и внешних провайдеров, когда применимо.

## 7. Ограничения

- Без подключения GitHub/Render/Meta я не могу опубликовать проект от твоего имени и создать реальные URL.
- Доступ Meta App Review и Advanced Access не выдаётся автоматически из кода.
- Render Free — бесплатный Web Service, но **не** бесплатная постоянная база данных; он засыпает при простое.
- Meta может запросить дополнительные сведения: категорию, видео работы, тестовый доступ, бизнес-проверку или уточнения по обработке данных.
