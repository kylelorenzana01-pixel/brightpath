import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()  # loads variables from .env file (for local development)

def db_connection():
    try:
        conn = mysql.connector.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            port=os.getenv('DB_PORT', 3306),           
            user=os.getenv('DB_USER', 'root'),
            password=os.getenv('DB_PASSWORD', ''),
            database=os.getenv('DB_NAME', 'bp_system_db')
        )
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return None
