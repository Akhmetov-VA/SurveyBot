# db.py

from pymongo import MongoClient

from config import MONGODB_DB_NAME, MONGODB_URI

client = MongoClient(MONGODB_URI)
db = client[MONGODB_DB_NAME]
