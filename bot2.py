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
        # Обработка CallbackQuery
        if query.data == "register":
            context.user_data["register_step"] = 1
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


# Логирование ошибок
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Произошла ошибка при обработке обновления:", exc_info=context.error)
    if update and update.effective_user:
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="Произошла ошибка. Пожалуйста, попробуйте позже.",
        )


# Добавляем обработчики
application.add_handler(CommandHandler("start", start))
application.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, register_user_step)
)
application.add_handler(CallbackQueryHandler(button_handler))
application.add_error_handler(error_handler)

# Запуск бота
if __name__ == "__main__":
    application.run_polling()
