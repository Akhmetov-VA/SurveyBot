# bot.py

import datetime
import logging
from io import BytesIO, StringIO

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bson import ObjectId
from pymongo import MongoClient
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import MONGODB_DB_NAME, MONGODB_URI, SUPER_USER_ID, TELEGRAM_BOT_TOKEN
from db import (
    assign_survey_to_user,
    get_scheduled_surveys,
    get_user_by_id,
    get_user_surveys,
    save_response,
    save_user_to_db,
    survey_templates_collection,
    surveys_collection,
    update_scheduled_survey,
)

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация бота и Application
application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()


# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = get_user_by_id(user_id)

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
        # Пользователь найден - показываем доступные опросы
        surveys = get_user_surveys(user_id)
        if surveys:
            keyboard = [
                [
                    InlineKeyboardButton(
                        f"Пройти опрос: {survey['title']}",
                        callback_data=f"start_survey_{survey['assigned_survey_id']}",
                    )
                ]
                for survey in surveys
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("Нет доступных опросов", callback_data="help")]
            ]
        keyboard.append(
            [
                InlineKeyboardButton(
                    "Связаться с администратором", callback_data="contact_admin"
                )
            ]
        )
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Добро пожаловать обратно! Выберите доступный пункт:",
            reply_markup=reply_markup,
        )


# Обработчик нажатий кнопок
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info(f"Button handler triggered: {update.callback_query.data}")

    query = update.callback_query
    if query:
        await query.answer()
        data = query.data

        if data == "register":
            context.user_data["register_step"] = 1
            await query.message.reply_text("Введите ваше имя:")

        elif data == "accept_personal_data":
            context.user_data["agree_personal_data"] = True
            await register_user_step(update, context, from_button=True)

        elif data == "decline_personal_data":
            context.user_data["agree_personal_data"] = False
            await register_user_step(update, context, from_button=True)

        elif data.startswith("start_survey_"):
            assigned_survey_id = data.split("_")[-1]
            context.user_data["current_assigned_survey_id"] = assigned_survey_id
            context.user_data["survey_step"] = 0
            await send_next_survey_question(update, context)

        elif data.startswith("csi_answer_"):
            await handle_csi_answer(update, context)

        elif data == "contact_admin":
            await contact_admin(update, context)

        else:
            await query.message.reply_text("Действие не распознано.")


# Регистрация пользователя
async def register_user_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE, from_button=False
) -> None:
    if from_button:
        message = update.callback_query.message
        text = None
    else:
        message = update.message
        text = update.message.text

    step = context.user_data.get("register_step", 1)

    if step == 1 and text:
        context.user_data["first_name"] = text
        await message.reply_text("Введите вашу фамилию:")
        context.user_data["register_step"] = 2
    elif step == 2 and text:
        context.user_data["last_name"] = text
        await message.reply_text("Введите вашу дату рождения (в формате ГГГГ-ММ-ДД):")
        context.user_data["register_step"] = 3
    elif step == 3 and text:
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
            await message.reply_text("Регистрация завершена! Добро пожаловать!")
            await handle_post_registration(update, context)
        else:
            await message.reply_text(
                "Вы отказались от регистрации. Мы не можем продолжить без согласия."
            )
        context.user_data.clear()
    else:
        await message.reply_text("Пожалуйста, следуйте инструкциям бота.")


# Обработка регистрации
async def handle_post_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    surveys = get_user_surveys(user_id)

    if surveys:
        # Если есть доступные опросы
        keyboard = [
            [
                InlineKeyboardButton(
                    f"Пройти опрос: {survey['title']}",
                    callback_data=f"start_survey_{survey['assigned_survey_id']}",
                )
            ]
            for survey in surveys
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


# Обработка команды /contact_admin
async def contact_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text(
        "Пожалуйста, введите сообщение для администратора."
    )
    context.user_data["contact_admin"] = True


# Обработка сообщений от пользователя
async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if context.user_data.get("contact_admin"):
        user_message = update.message.text
        admin_id = (
            SUPER_USER_ID  # Задайте ID администратора в config.py или прямо здесь
        )
        # Отправка сообщения администратору
        await context.bot.send_message(
            chat_id=admin_id,
            text=f"Сообщение от пользователя {user_id}:\n{user_message}",
        )
        await update.message.reply_text("Ваше сообщение отправлено администратору.")
        context.user_data.pop("contact_admin", None)
    elif context.user_data.get("register_step"):
        # Если пользователь в процессе регистрации
        await register_user_step(update, context)
    elif context.user_data.get("current_assigned_survey_id"):
        # Если пользователь проходит опрос
        await handle_open_answer(update, context)
    else:
        await update.message.reply_text(
            "Пожалуйста, используйте кнопки для взаимодействия."
        )


# Отправка следующего вопроса опроса
async def send_next_survey_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    assigned_survey_id = context.user_data.get("current_assigned_survey_id")
    if not assigned_survey_id:
        await update.effective_message.reply_text("Ошибка: опрос не найден.")
        return

    try:
        assigned_survey = surveys_collection.find_one(
            {"_id": ObjectId(assigned_survey_id)}
        )
        if not assigned_survey:
            await update.effective_message.reply_text("Опрос не найден.")
            return
        survey_template_id = assigned_survey["survey_template_id"]
        survey_template = survey_templates_collection.find_one(
            {"_id": survey_template_id}
        )
    except Exception as e:
        logger.error(f"Ошибка при поиске опроса: {e}")
        await update.effective_message.reply_text("Ошибка загрузки опроса.")
        return

    if not survey_template:
        await update.effective_message.reply_text("Опрос не найден.")
        return

    step = context.user_data.get("survey_step", 0)
    questions = survey_template.get("questions", [])
    if step < len(questions):
        question = questions[step]
        context.user_data["current_question"] = question
        if question["type"] == "csi":
            keyboard = [
                [InlineKeyboardButton(str(i), callback_data=f"csi_answer_{i}")]
                for i in range(1, 6)
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.effective_message.reply_text(
                question["text"], reply_markup=reply_markup
            )
        elif question["type"] == "open":
            await update.effective_message.reply_text(question["text"])
    else:
        await update.effective_message.reply_text("Опрос завершён. Спасибо за участие!")
        # Mark survey as completed
        surveys_collection.update_one(
            {"_id": ObjectId(assigned_survey_id)},
            {"$set": {"completed": True, "completed_at": datetime.datetime.utcnow()}},
        )
        context.user_data.pop("current_assigned_survey_id", None)
        context.user_data.pop("survey_step", None)
        context.user_data.pop("current_question", None)


# Обработка ответа на CSI вопрос
async def handle_csi_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    answer = int(query.data.split("_")[2])
    user_id = update.effective_user.id
    question = context.user_data.get("current_question")
    assigned_survey_id = context.user_data.get("current_assigned_survey_id")

    if question and assigned_survey_id:
        assigned_survey = surveys_collection.find_one(
            {"_id": ObjectId(assigned_survey_id)}
        )
        survey_template_id = assigned_survey["survey_template_id"]
        save_response(
            {
                "user_id": user_id,
                "assigned_survey_id": ObjectId(assigned_survey_id),
                "survey_template_id": survey_template_id,
                "question": question["text"],
                "answer": answer,
                "type": "csi",
            }
        )
        context.user_data["survey_step"] += 1
        await query.answer()
        await send_next_survey_question(update, context)
    else:
        await query.message.reply_text("Ошибка при сохранении ответа.")


# Обработка ответа на открытый вопрос
async def handle_open_answer(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    text = update.message.text
    user_id = update.effective_user.id
    question = context.user_data.get("current_question")
    assigned_survey_id = context.user_data.get("current_assigned_survey_id")

    if question and assigned_survey_id:
        assigned_survey = surveys_collection.find_one(
            {"_id": ObjectId(assigned_survey_id)}
        )
        survey_template_id = assigned_survey["survey_template_id"]
        save_response(
            {
                "user_id": user_id,
                "assigned_survey_id": ObjectId(assigned_survey_id),
                "survey_template_id": survey_template_id,
                "question": question["text"],
                "answer": text,
                "type": "open",
            }
        )
        context.user_data["survey_step"] += 1
        await send_next_survey_question(update, context)
    else:
        await update.message.reply_text("Ошибка при сохранении ответа.")


# Обработка ошибок
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Произошла ошибка при обработке обновления:", exc_info=context.error)
    if update and hasattr(update, "effective_user") and update.effective_user:
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="Произошла ошибка. Пожалуйста, попробуйте позже.",
        )


# Проверка расписания и отправка опросов
async def check_scheduled_surveys(context: ContextTypes.DEFAULT_TYPE):
    scheduled_surveys = get_scheduled_surveys()
    now = datetime.datetime.utcnow()
    for scheduled_survey in scheduled_surveys:
        next_run = scheduled_survey.get("next_run")
        if next_run and next_run <= now:
            user_id = scheduled_survey["user_id"]
            survey_template_id = scheduled_survey["survey_template_id"]
            assign_survey_to_user(user_id, survey_template_id)
            # Обновить время следующего запуска на основе расписания
            # Здесь вы можете использовать schedule_data для вычисления следующего запуска
            # Для простоты предположим, что опрос повторяется ежедневно
            next_run = now + datetime.timedelta(days=1)
            update_scheduled_survey(scheduled_survey["_id"], next_run)
            # Уведомляем пользователя
            await context.bot.send_message(
                chat_id=user_id,
                text="У вас есть новый опрос для прохождения. Пожалуйста, используйте команду /start",
            )


# Добавление обработчиков
application.add_handler(MessageHandler(filters.Command("start"), start), group=0)
application.add_handler(CallbackQueryHandler(button_handler), group=1)
application.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message), group=2
)
application.add_error_handler(error_handler)

# Настройка планировщика
scheduler = AsyncIOScheduler()
scheduler.add_job(check_scheduled_surveys, "interval", minutes=1, args=[application])
scheduler.start()

# Запуск бота
if __name__ == "__main__":
    application.run_polling()
