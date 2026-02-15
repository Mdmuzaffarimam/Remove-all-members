import sqlite3
from datetime import datetime

DB_NAME = "sudo.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sudo_users (
            user_id INTEGER PRIMARY KEY,
            added_on TEXT
        )
    """)

    conn.commit()
    conn.close()


def add_sudo(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute(
        "INSERT OR IGNORE INTO sudo_users VALUES (?, ?)",
        (user_id, datetime.now().strftime("%d-%m-%Y %H:%M:%S"))
    )

    conn.commit()
    conn.close()


def del_sudo(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("DELETE FROM sudo_users WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def get_all_sudo():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("SELECT user_id FROM sudo_users")
    users = [x[0] for x in cur.fetchall()]

    conn.close()
    return users


def is_sudo(user_id: int):
    return user_id in get_all_sudo()
