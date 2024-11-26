# config.py

import os

from dotenv import load_dotenv

SUPER_USER_ID = 77269896

# Load environment variables
load_dotenv()

MONGO_USERNAME = os.getenv("MONGO_INITDB_ROOT_USERNAME")
MONGO_PASSWORD = os.getenv("MONGO_INITDB_ROOT_PASSWORD")
MONGO_HOST = os.getenv("MONGO_HOST")
MONGO_PORT = os.getenv("MONGO_INITDB_ROOT_PORT")

# Параметры для Telegram-бота
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Параметры для MongoDB
MONGODB_URI = f"mongodb://{MONGO_USERNAME}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}/"
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "tgbot")

# Список Telegram ID администраторов
ADMIN_IDS = [
    int(admin_id) for admin_id in os.getenv("ADMIN_IDS", "").split(",") if admin_id
]
