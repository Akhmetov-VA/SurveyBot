# streamlit_app.py

import datetime
from collections import Counter

import matplotlib.pyplot as plt
import nltk
import numpy as np
import pandas as pd
import pymorphy2
import streamlit as st
from bson import ObjectId
from nltk.corpus import stopwords
from nltk.sentiment import SentimentIntensityAnalyzer
from nltk.tokenize import word_tokenize
from telegram import Bot
from wordcloud import WordCloud

from config import TELEGRAM_BOT_TOKEN
from db import (  # Changed from 'db' to 'database'
    assign_survey_to_status,
    assign_survey_to_user,
    create_status,
    create_survey_template,
    get_all_users,
    get_scheduled_surveys,
    get_survey_responses,
    get_survey_templates,
    get_survey_title,
    get_surveys_for_status,
    get_user_full_name,
    get_user_statuses,
    get_user_surveys,
    get_users_by_status,
    schedule_survey,
    update_user_status,
)

nltk.download("punkt_tab")

bot = Bot(token=TELEGRAM_BOT_TOKEN)

st.title("Панель администратора")

menu = ["Пользователи", "Опросы", "Расписание", "Статусы"]
tabs = st.tabs(menu)

with tabs[0]:
    st.header("Управление пользователями")
    users = get_all_users()
    user_df = pd.DataFrame(users)
    required_columns = ["first_name", "last_name", "user_id", "status"]

    # Reindex the DataFrame to include all required columns
    user_df = user_df.reindex(columns=required_columns)

    # Fill missing values in 'status' with a default value
    user_df["status"].fillna("unknown", inplace=True)

    if not user_df.empty:
        user_df["Полное имя"] = user_df["first_name"] + " " + user_df["last_name"]
        st.write(user_df[["Полное имя", "user_id", "status"]])
    else:
        st.write("Нет пользователей")

    # Управление статусами пользователей
    st.subheader("Изменить статус пользователя")
    user_options = {
        f"{u.get('first_name', '')} {u.get('last_name', '')} (ID: {u['user_id']})": u[
            "user_id"
        ]
        for u in users
    }
    selected_user = st.selectbox(
        "Выберите пользователя", list(user_options.keys()), key="пользователя"
    )
    selected_user_id = user_options[selected_user]

    statuses = get_user_statuses()
    status_options = [status["name"] for status in statuses]
    selected_status = st.selectbox(
        "Выберите новый статус", status_options, key="статус"
    )

    if st.button("Обновить статус"):
        update_user_status(selected_user_id, selected_status)
        st.success(f"Статус пользователя обновлен на {selected_status}")
        # Отправить сообщение пользователю
        assigned_surveys = get_user_surveys(selected_user_id)
        survey_titles = [survey["title"] for survey in assigned_surveys]
        message = f"Ваш статус изменен на {selected_status}. Вам назначены следующие опросы: {', '.join(survey_titles)}"
        try:
            bot.send_message(chat_id=selected_user_id, text=message)
        except Exception as e:
            st.error(f"Не удалось отправить сообщение пользователю: {e}")

with tabs[1]:
    st.header("Управление опросами")

    action = st.selectbox(
        "Действие",
        ["Создать опрос", "Просмотреть опросы", "Просмотреть результаты"],
        key="Действие",
    )

    if action == "Создать опрос":
        st.subheader("Создание нового опроса")
        title = st.text_input("Название опроса")
        questions = []

        if "questions" not in st.session_state:
            st.session_state["questions"] = []

        question_type = st.selectbox(
            "Тип вопроса", ["CSI вопрос", "Открытый вопрос"], key="Тип"
        )
        question_text = st.text_input("Текст вопроса")

        if st.button("Добавить вопрос"):
            st.session_state["questions"].append(
                {
                    "type": "csi" if question_type == "CSI вопрос" else "open",
                    "text": question_text,
                }
            )
            st.success("Вопрос добавлен")

        st.write("Добавленные вопросы:")
        csi_questions = [q for q in st.session_state["questions"] if q["type"] == "csi"]
        open_questions = [
            q for q in st.session_state["questions"] if q["type"] == "open"
        ]

        if csi_questions:
            st.write("CSI вопросы:")
            for idx, q in enumerate(csi_questions):
                st.write(f"{idx+1}. {q['text']}")

        if open_questions:
            st.write("Открытые вопросы:")
            for idx, q in enumerate(open_questions):
                st.write(f"{idx+1}. {q['text']}")

        if st.button("Сохранить опрос"):
            if title and st.session_state["questions"]:
                survey_data = {
                    "title": title,
                    "questions": st.session_state["questions"],
                    "created_at": datetime.datetime.utcnow(),
                }
                create_survey_template(survey_data)
                st.success("Опрос успешно сохранён")
                st.session_state["questions"] = []
            else:
                st.error("Введите название опроса и добавьте хотя бы один вопрос")

    elif action == "Просмотреть опросы":
        st.subheader("Список опросов")
        surveys = get_survey_templates()
        for survey in surveys:
            st.write(f"Название: {survey.get('title', '')}")
            csi_questions = [
                q for q in survey.get("questions", []) if q["type"] == "csi"
            ]
            open_questions = [
                q for q in survey.get("questions", []) if q["type"] == "open"
            ]

            if csi_questions:
                st.write("CSI вопросы:")
                for q in csi_questions:
                    st.write(f"- {q['text']}")
            if open_questions:
                st.write("Открытые вопросы:")
                for q in open_questions:
                    st.write(f"- {q['text']}")
            st.write("---")

    elif action == "Просмотреть результаты":
        st.subheader("Результаты опросов")
        surveys = get_survey_templates()
        survey_options = {
            survey.get("title", ""): str(survey["_id"]) for survey in surveys
        }
        selected_survey_title = st.selectbox(
            "Выберите опрос", list(survey_options.keys()), key="опрос"
        )
        selected_survey_id = survey_options[selected_survey_title]
        responses = get_survey_responses(selected_survey_id)

        if responses:
            df_responses = pd.DataFrame(responses)
            csi_responses = df_responses[df_responses["type"] == "csi"]
            open_responses = df_responses[df_responses["type"] == "open"]

            if not csi_responses.empty:
                st.write("Результаты CSI вопросов")
                # Аналитика CSI
                csi_responses["answer"] = csi_responses["answer"].astype(int)
                csi_stats = csi_responses.groupby("question")["answer"].agg(
                    ["mean", "std", "count"]
                )
                st.table(csi_stats)

                # Гистограмма распределения
                st.write("Распределение ответов")
                fig, ax = plt.subplots()
                csi_responses["answer"].hist(bins=5, ax=ax)
                st.pyplot(fig)

            if not open_responses.empty:
                st.write("Результаты открытых вопросов")
                # Обработка текста
                nltk.download("punkt")
                nltk.download("stopwords")
                stop_words = set(stopwords.words("russian"))
                morph = pymorphy2.MorphAnalyzer()
                all_text = " ".join(open_responses["answer"])
                tokens = word_tokenize(all_text.lower())
                tokens = [
                    morph.parse(word)[0].normal_form
                    for word in tokens
                    if word.isalpha() and word not in stop_words
                ]
                word_counts = Counter(tokens)
                top_words = word_counts.most_common(10)
                st.write("Топ 10 слов:")
                for word, count in top_words:
                    st.write(f"{word}: {count}")

                # Облако слов
                st.write("Облако слов:")
                wordcloud = WordCloud(width=800, height=400).generate_from_frequencies(
                    word_counts
                )
                fig, ax = plt.subplots(figsize=(15, 7.5))
                ax.imshow(wordcloud, interpolation="bilinear")
                ax.axis("off")
                st.pyplot(fig)

                # Сентимент анализ
                nltk.download("vader_lexicon")
                sia = SentimentIntensityAnalyzer()
                open_responses["sentiment"] = open_responses["answer"].apply(
                    lambda x: sia.polarity_scores(x)["compound"]
                )
                st.write("Сентимент анализ:")
                st.bar_chart(open_responses["sentiment"])

        else:
            st.write("Нет ответов для этого опроса.")

with tabs[2]:
    st.header("Планирование опросов")
    users = get_all_users()
    user_options = {
        f"{u.get('first_name', '')} {u.get('last_name', '')} (ID: {u['user_id']})": u[
            "user_id"
        ]
        for u in users
    }
    statuses = get_user_statuses()
    status_options = [status["name"] for status in statuses]
    selection_type = st.radio("Выберите тип назначения", ["Пользователь", "Статус"])

    if selection_type == "Пользователь":
        selected_user = st.selectbox(
            "Выберите пользователя",
            list(user_options.keys()),
            key="Выберите пользователя",
        )
        selected_user_id = user_options[selected_user]
        target_ids = [selected_user_id]
    else:
        selected_status = st.selectbox(
            "Выберите статус", status_options, key="Выберите статус"
        )
        users_with_status = get_users_by_status(selected_status)
        target_ids = [user["user_id"] for user in users_with_status]

    surveys = get_survey_templates()
    survey_options = {
        s.get("title", f"Опрос {s['_id']}"): str(s["_id"]) for s in surveys
    }
    selected_survey = st.selectbox(
        "Выберите опрос", list(survey_options.keys()), key="Выберите опрос 2"
    )
    selected_survey_id = survey_options[selected_survey]

    frequency = st.selectbox(
        "Частота отправки",
        ["Ежедневно", "Еженедельно", "Ежемесячно"],
        key="Частота отправки1",
    )
    start_date = st.date_input("Дата начала", datetime.date.today())

    if st.button("Запланировать опрос"):
        schedule_data = {
            "frequency": frequency,
            "start_date": datetime.datetime.combine(
                start_date, datetime.datetime.min.time()
            ),
        }
        for user_id in target_ids:
            schedule_survey(user_id, selected_survey_id, schedule_data)
        st.success("Опрос успешно запланирован")

    # Визуализация запланированных опросов
    st.subheader("Запланированные опросы")
    scheduled_surveys = get_scheduled_surveys()
    if scheduled_surveys:
        scheduled_df = pd.DataFrame(scheduled_surveys)
        scheduled_df["survey_title"] = scheduled_df["survey_template_id"].apply(
            lambda x: get_survey_title(str(x))
        )
        scheduled_df["user"] = scheduled_df["user_id"].apply(
            lambda x: get_user_full_name(x)
        )
        st.table(scheduled_df[["user", "survey_title", "schedule"]])
    else:
        st.write("Нет запланированных опросов")

with tabs[3]:
    st.header("Управление статусами")
    statuses = get_user_statuses()
    status_names = [status["name"] for status in statuses]
    st.write("Существующие статусы:")
    st.write(status_names)

    st.subheader("Добавить новый статус")
    new_status_name = st.text_input("Название статуса")
    if st.button("Добавить статус"):
        if new_status_name:
            create_status(new_status_name)
            st.success("Статус добавлен")
        else:
            st.error("Введите название статуса")

    st.subheader("Назначить опрос статусу")
    selected_status = st.selectbox(
        "Выберите статус", status_names, key="assign_survey_status"
    )
    surveys = get_survey_templates()
    survey_options = {
        s.get("title", f"Опрос {s['_id']}"): str(s["_id"]) for s in surveys
    }
    selected_survey = st.selectbox(
        "Выберите опрос", list(survey_options.keys()), key="assign_survey_survey"
    )
    selected_survey_id = survey_options[selected_survey]

    if st.button("Назначить опрос статусу"):
        assign_survey_to_status(selected_status, selected_survey_id)
        st.success("Опрос назначен статусу")

    st.subheader("Опросы для статуса")
    selected_status = st.selectbox(
        "Выберите статус для просмотра опросов", status_names, key="view_status_surveys"
    )
    surveys_for_status = get_surveys_for_status(selected_status)
    if surveys_for_status:
        st.write(f"Опросы для статуса {selected_status}:")
        for survey in surveys_for_status:
            st.write(f"- {survey.get('title', '')}")
    else:
        st.write("Нет назначенных опросов для этого статуса")
