"""
SQLite database for storing BME280 sensor readings.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "sensor_data.db"


def init_db():
    """Create the database and table if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            temperature REAL NOT NULL,
            humidity REAL NOT NULL,
            pressure REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def save_reading(temperature, humidity, pressure):
    """Save a sensor reading to the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO readings (timestamp, temperature, humidity, pressure) VALUES (?, ?, ?, ?)",
        (datetime.now().isoformat(), temperature, humidity, pressure)
    )
    conn.commit()
    conn.close()


def get_readings(limit=100):
    """Get the most recent readings."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT timestamp, temperature, humidity, pressure FROM readings ORDER BY id DESC LIMIT ?",
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()
    # Return in chronological order
    return list(reversed(rows))


def get_readings_since(hours=1):
    """Get readings from the last N hours."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """SELECT timestamp, temperature, humidity, pressure
           FROM readings
           WHERE timestamp >= datetime('now', '-' || ? || ' hours', 'localtime')
           ORDER BY id ASC""",
        (hours,)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_latest_reading():
    """Get the most recent reading."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT timestamp, temperature, humidity, pressure FROM readings ORDER BY id DESC LIMIT 1"
    )
    row = cursor.fetchone()
    conn.close()
    return row


# Initialize database on import
init_db()
