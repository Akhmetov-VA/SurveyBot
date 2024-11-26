# database.py

import datetime

from bson import ObjectId
from pymongo import MongoClient

from config import MONGODB_DB_NAME, MONGODB_URI

# Подключение к MongoDB
try:
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    client.server_info()  # Проверяем соединение
    db = client[MONGODB_DB_NAME]
    users_collection = db["users"]
    surveys_collection = db["surveys"]  # Assigned surveys to users
    survey_templates_collection = db["survey_templates"]
    responses_collection = db["responses"]
    scheduled_surveys_collection = db["scheduled_surveys"]
    status_collection = db["statuses"]  # Collection for user statuses
    survey_status_collection = db[
        "survey_status"
    ]  # Collection for surveys assigned to statuses
except Exception as e:
    print(f"Ошибка подключения к MongoDB: {e}")
    raise RuntimeError("Невозможно подключиться к базе данных MongoDB.")


# Функции для работы с пользователями
def save_user_to_db(user_id, user_data):
    users_collection.insert_one(
        {
            "user_id": user_id,
            "first_name": user_data["first_name"],
            "last_name": user_data["last_name"],
            "birth_date": user_data["birth_date"],
            "new_user": True,
            "role": "user",
            "status": "default",  # Assign a default status if needed
        }
    )


def get_user_by_id(user_id):
    return users_collection.find_one({"user_id": user_id})


def get_all_users():
    return list(users_collection.find())


def get_user_full_name(user_id):
    user = users_collection.find_one({"user_id": user_id})
    if user:
        return f"{user.get('first_name', '')} {user.get('last_name', '')}"
    return "Неизвестный пользователь"


def update_user_status(user_id, new_status):
    users_collection.update_one({"user_id": user_id}, {"$set": {"status": new_status}})
    # When status changes, assign surveys associated with the new status
    surveys = get_surveys_for_status(new_status)
    for survey in surveys:
        assign_survey_to_user(user_id, survey["_id"])


def get_users_by_status(status_name):
    return list(users_collection.find({"status": status_name}))


def get_user_statuses():
    return list(status_collection.find({}, {"_id": 0, "name": 1}))


def create_status(status_name):
    existing_status = status_collection.find_one({"name": status_name})
    if not existing_status:
        status_collection.insert_one(
            {"name": status_name, "created_at": datetime.datetime.utcnow()}
        )


# Функции для работы с опросами
def create_survey_template(survey_data):
    survey_templates_collection.insert_one(survey_data)


def get_survey_templates():
    return list(survey_templates_collection.find())


def get_survey_title(survey_id):
    survey = survey_templates_collection.find_one({"_id": ObjectId(survey_id)})
    return survey.get("title", "Без названия") if survey else None


def assign_survey_to_user(user_id, survey_template_id):
    existing_assignment = surveys_collection.find_one(
        {
            "user_id": user_id,
            "survey_template_id": ObjectId(survey_template_id),
            "completed": False,
        }
    )
    if not existing_assignment:
        surveys_collection.insert_one(
            {
                "user_id": user_id,
                "survey_template_id": ObjectId(survey_template_id),
                "assigned_at": datetime.datetime.utcnow(),
                "completed": False,
            }
        )


def assign_survey_to_status(status_name, survey_template_id):
    existing_assignment = survey_status_collection.find_one(
        {"status_name": status_name, "survey_template_id": ObjectId(survey_template_id)}
    )
    if not existing_assignment:
        survey_status_collection.insert_one(
            {
                "status_name": status_name,
                "survey_template_id": ObjectId(survey_template_id),
                "assigned_at": datetime.datetime.utcnow(),
            }
        )
        # Assign this survey to all users with this status
        users = get_users_by_status(status_name)
        for user in users:
            assign_survey_to_user(user["user_id"], survey_template_id)


def get_surveys_for_status(status_name):
    assignments = survey_status_collection.find({"status_name": status_name})
    survey_ids = [a["survey_template_id"] for a in assignments]
    return list(survey_templates_collection.find({"_id": {"$in": survey_ids}}))


def get_user_surveys(user_id):
    assigned_surveys = surveys_collection.find({"user_id": user_id, "completed": False})
    surveys = []
    for assigned_survey in assigned_surveys:
        survey_template_id = assigned_survey["survey_template_id"]
        survey_template = survey_templates_collection.find_one(
            {"_id": survey_template_id}
        )
        if survey_template:
            surveys.append(
                {
                    "assigned_survey_id": str(assigned_survey["_id"]),
                    "title": survey_template.get("title", "Без названия"),
                    "questions": survey_template.get("questions", []),
                }
            )
    return surveys


def save_response(response_data):
    responses_collection.insert_one(response_data)


def get_survey_responses(survey_id):
    return list(responses_collection.find({"survey_template_id": ObjectId(survey_id)}))


# Функции для работы с расписанием опросов
def get_scheduled_surveys():
    scheduled_surveys = list(scheduled_surveys_collection.find())
    for survey in scheduled_surveys:
        survey["survey_template_id"] = str(survey["survey_template_id"])
    return scheduled_surveys


def schedule_survey(user_id, survey_template_id, schedule_data):
    scheduled_surveys_collection.insert_one(
        {
            "user_id": user_id,
            "survey_template_id": ObjectId(survey_template_id),
            "schedule": schedule_data,  # Данные о расписании (например, частота, дата начала)
            "next_run": schedule_data["start_date"],
        }
    )


def update_scheduled_survey(scheduled_survey_id, next_run):
    scheduled_surveys_collection.update_one(
        {"_id": scheduled_survey_id},
        {"$set": {"next_run": next_run}},
    )


def add_status_to_existing_users():
    users_collection.update_many(
        {"status": {"$exists": False}}, {"$set": {"status": "default"}}
    )


if __name__ == "__main__":
    add_status_to_existing_users()
    print("All existing users have been updated with a default status.")
