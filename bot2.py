import datetime
import logging

from pymongo import MongoClient
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import MONGODB_DB_NAME, MONGODB_URI, TELEGRAM_BOT_TOKEN

# ID суперпользователя
super_user_id = 77269896

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# Сохранение данных пользователя в базу
def save_user_to_db(user_id, user_data):
    users_collection.insert_one(
        {
            "user_id": user_id,
            "first_name": user_data["first_name"],
            "last_name": user_data["last_name"],
            "birth_date": user_data["birth_date"],
            "new_user": True,
            "role": "user",
        }
    )


# Проверка наличия доступных опросов
def get_user_surveys(user_id):
    return list(surveys_collection.find({"user_id": user_id}))


# Отправка сообщений после регистрации
async def handle_post_registration(update, user_id):
    # Проверяем наличие опросов
    surveys = get_user_surveys(user_id)

    if surveys:
        # Если есть доступные опросы
        keyboard = [
            [
                InlineKeyboardButton(
                    "Пройти опрос", callback_data=f"survey_{surveys[0]['_id']}"
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Регистрация завершена! Добро пожаловать! У вас есть доступные опросы.",
            reply_markup=reply_markup,
        )
    else:
        # Если опросов нет
        await update.message.reply_text(
            "Регистрация завершена! Кажется, для вас нет опросов. Администратор скоро добавит их в бот."
        )


# Подключение к MongoDB
try:
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    client.server_info()  # Проверяем соединение
    db = client[MONGODB_DB_NAME]
    users_collection = db["users"]
    surveys_collection = db["surveys"]
    survey_templates_collection = db["survey_templates"]

except Exception as e:
    logger.error(f"Ошибка подключения к MongoDB: {e}")
    exit()

# Инициализация бота и Application
application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = users_collection.find_one({"user_id": user_id})

    if not user:
        # Пользователь не найден в базе данных - предлагаем зарегистрироваться
        keyboard = [
            [InlineKeyboardButton("Зарегистрироваться", callback_data="register")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Добро пожаловать! Вы не зарегистрированы. Пожалуйста, нажмите кнопку ниже для регистрации:",
            reply_markup=reply_markup,
        )
    else:
        # Пользователь найден - проверяем его роль
        role = user.get("role", "user")  # По умолчанию роль - обычный пользователь

        if role == "admin":
            # Если админ - показываем админ панель
            keyboard = [
                [
                    InlineKeyboardButton(
                        "Панель администратора", callback_data="admin_panel"
                    )
                ],
                [InlineKeyboardButton("Помощь", callback_data="help")],
            ]
        else:
            # Если обычный пользователь - показываем доступные опросы
            survey_count = surveys_collection.count_documents(
                {"user_id": user_id}
            )  # Исправлено
            if survey_count > 0:
                surveys = surveys_collection.find({"user_id": user_id})
                keyboard = [
                    [
                        InlineKeyboardButton(
                            f"Опрос {survey['title']}",
                            callback_data=f"survey_{survey['_id']}",
                        )
                    ]
                    for survey in surveys
                ]
            else:
                keyboard = [
                    [
                        InlineKeyboardButton(
                            "Нет доступных опросов", callback_data="help"
                        )
                    ]
                ]
            keyboard.append([InlineKeyboardButton("Помощь", callback_data="help")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Добро пожаловать обратно! Выберите доступный пункт:",
            reply_markup=reply_markup,
        )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()

        # Обработка нажатий кнопок
        if query.data == "register":
            context.user_data["register_step"] = "register"
            await query.message.reply_text("Введите ваше имя:")

        elif query.data == "accept_personal_data":
            context.user_data["agree_personal_data"] = True
            await query.message.reply_text(
                "Спасибо за согласие. Регистрация продолжается..."
            )
            await register_user_step(update, context, from_button=True)

        elif query.data == "decline_personal_data":
            context.user_data["agree_personal_data"] = False
            await query.message.reply_text(
                "Регистрация завершена. Вы отказались от согласия."
            )
            context.user_data.clear()

        elif query.data == "admin_panel":
            # Логика для панели администратора
            keyboard = [
                [
                    InlineKeyboardButton(
                        "Создать опрос", callback_data="create_survey"
                    ),
                    InlineKeyboardButton(
                        "Показать статистику", callback_data="show_stats"
                    ),
                ],
                [InlineKeyboardButton("Выйти", callback_data="exit_admin_panel")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(
                "Добро пожаловать в панель администратора:", reply_markup=reply_markup
            )

        elif query.data == "create_survey":
            # Переход к созданию опроса
            await admin_create_survey(update, context)

        elif query.data == "show_stats":
            # Заглушка для показа статистики
            await query.message.reply_text("Показ статистики пока не реализован.")

        elif query.data == "exit_admin_panel":
            # Возврат из панели администратора
            await query.message.reply_text("Вы покинули панель администратора.")

        else:
            await query.message.reply_text("Действие обработано.")


# Обновленный register_user_step с вызовом этих функций
async def register_user_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE, from_button=False
) -> None:
    # Определяем источник данных
    if from_button:
        message = update.callback_query.message
        text = context.user_data.get("temp_text", "")  # Временный текст, если нужен
    else:
        message = update.message
        text = update.message.text

    step = context.user_data.get("register_step", 1)

    if step == 1:
        context.user_data["first_name"] = text
        await message.reply_text("Введите вашу фамилию:")
        context.user_data["register_step"] = 2
    elif step == 2:
        context.user_data["last_name"] = text
        await message.reply_text("Введите вашу дату рождения (в формате ГГГГ-ММ-ДД):")
        context.user_data["register_step"] = 3
    elif step == 3:
        try:
            birth_date = datetime.datetime.strptime(text, "%Y-%m-%d").date()
            context.user_data["birth_date"] = str(birth_date)
            keyboard = [
                [
                    InlineKeyboardButton(
                        "Согласен", callback_data="accept_personal_data"
                    ),
                    InlineKeyboardButton(
                        "Не согласен", callback_data="decline_personal_data"
                    ),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await message.reply_text(
                "Вы соглашаетесь на обработку персональных данных?",
                reply_markup=reply_markup,
            )
            context.user_data["register_step"] = 4
        except ValueError:
            await message.reply_text(
                "Некорректный формат даты. Попробуйте еще раз (ГГГГ-ММ-ДД)."
            )
    elif step == 4:
        if context.user_data.get("agree_personal_data"):
            # Сохраняем пользователя
            save_user_to_db(update.effective_user.id, context.user_data)
            # Обрабатываем сообщения после регистрации
            await handle_post_registration(update, update.effective_user.id)
        else:
            await message.reply_text(
                "Вы отказались от регистрации. Мы не можем продолжить без согласия."
            )
        context.user_data.clear()


async def admin_create_survey(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    # Получаем сообщение из callback_query
    query = update.callback_query
    message = query.message

    # Отправляем сообщение с выбором типа вопроса
    keyboard = [
        [
            InlineKeyboardButton("CSI вопрос", callback_data="create_csi_question"),
            InlineKeyboardButton(
                "Открытый вопрос", callback_data="create_open_question"
            ),
        ],
        [InlineKeyboardButton("Закончить создание", callback_data="finish_survey")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text(
        "Выберите тип вопроса для создания опроса:", reply_markup=reply_markup
    )


async def handle_admin_buttons(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query.data == "create_csi_question":
        context.user_data["survey_step"] = "add_csi_question"
        await query.message.reply_text("Введите текст CSI вопроса (от 1 до 5):")
    elif query.data == "create_open_question":
        context.user_data["survey_step"] = "add_open_question"
        await query.message.reply_text("Введите текст открытого вопроса:")
    elif query.data == "finish_survey":
        if query.data == "finish_survey":
            current_survey = context.user_data.pop("current_survey", [])
        if current_survey:
            survey_templates_collection.insert_one({"questions": current_survey})
            await query.message.reply_text("Опрос успешно сохранён!")
        else:
            await query.message.reply_text("Опрос пуст. Ничего не сохранено.")


async def save_survey_question(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    step = context.user_data.get("survey_step")
    text = update.message.text

    if step == "add_csi_question":
        question = {"type": "csi", "question": text}
    elif step == "add_open_question":
        question = {"type": "open", "question": text}
    else:
        return

    # Добавляем вопрос в текущий опрос
    if "current_survey" not in context.user_data:
        context.user_data["current_survey"] = []
    context.user_data["current_survey"].append(question)

    await update.message.reply_text(
        "Вопрос добавлен. Вы можете добавить еще вопросы или завершить создание."
    )


async def show_survey(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    surveys = surveys_collection.find({"user_id": user_id, "completed": False})

    for survey in surveys:
        for question in survey.get("questions", []):
            if question["type"] == "csi":
                keyboard = [
                    [InlineKeyboardButton(str(i), callback_data=f"csi_answer_{i}")]
                    for i in range(1, 6)
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    question["question"], reply_markup=reply_markup
                )
            elif question["type"] == "open":
                await update.message.reply_text(question["question"])

        # Помечаем опрос как завершённый
        surveys_collection.update_one(
            {"_id": survey["_id"]}, {"$set": {"completed": True}}
        )


async def handle_csi_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    answer = int(query.data.split("_")[2])
    user_id = update.effective_user.id
    surveys_collection.insert_one({"user_id": user_id, "type": "csi", "answer": answer})
    await query.answer()
    await query.message.reply_text(f"Ваш ответ: {answer}")


async def handle_open_answer(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    text = update.message.text
    user_id = update.effective_user.id
    surveys_collection.insert_one({"user_id": user_id, "type": "open", "answer": text})
    await update.message.reply_text(f"Ваш ответ: {text}")


# Логирование ошибок
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Произошла ошибка при обработке обновления:", exc_info=context.error)
    logger.error(f"Update: {update}")
    logger.error(f"Context error: {context.error}")
    if update and update.effective_user:
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="Произошла ошибка. Пожалуйста, попробуйте позже.",
        )


async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    step = context.user_data.get("survey_step")

    if step == "register":  # Если пользователь в процессе регистрации
        await register_user_step(update, context)
    elif step in [
        "add_csi_question",
        "add_open_question",
    ]:  # Если админ добавляет вопросы
        await save_survey_question(update, context)
    else:  # Если пользователь отвечает на открытый вопрос
        await handle_open_answer(update, context)


# Добавляем обработчики
application.add_handler(CommandHandler("start", start))  # Стартовая команда
application.add_handler(CallbackQueryHandler(button_handler))  # Общие кнопки
application.add_handler(
    CommandHandler("create_survey", admin_create_survey)
)  # Создание опроса
application.add_handler(
    CallbackQueryHandler(handle_admin_buttons, pattern="create_.*")
)  # Кнопки для админа
application.add_handler(
    CallbackQueryHandler(handle_csi_answer, pattern="csi_answer_.*")
)  # Ответы на CSI вопросы

# Маршрутизатор текстовых сообщений
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))

# Логирование ошибок
application.add_error_handler(error_handler)


# Запуск бота
if __name__ == "__main__":
    application.run_polling()
