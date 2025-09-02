#!/usr/bin/env python3
import sqlite3
import os
from PIL import Image
import io

DB_FILE = "jail_records.db"

def view_database():
    """View all records in the database"""
    if not os.path.exists(DB_FILE):
        print(f"Database {DB_FILE} not found!")
        return
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Get total count
    cursor.execute("SELECT COUNT(*) FROM jail_records")
    total = cursor.fetchone()[0]
    print(f"Total records in database: {total}\n")
    
    # Get all records
    cursor.execute("""
        SELECT id, first_name, middle_name, last_name, booking_date, 
               date_of_birth, gender, arrestor, charges, source_pdf
        FROM jail_records 
        ORDER BY booking_date
    """)
    
    records = cursor.fetchall()
    
    for record in records:
        id_num, first, middle, last, booking, dob, gender, arrestor, charges, source = record
        print(f"ID: {id_num}")
        print(f"Name: {first} {middle} {last}".strip())
        print(f"Booking: {booking}")
        print(f"DOB: {dob}")
        print(f"Gender: {gender}")
        print(f"Arrestor: {arrestor}")
        print(f"Charges: {charges}")
        print(f"Source: {source}")
        print("-" * 50)
    
    conn.close()

def save_image_from_db(record_id, output_filename):
    """Save an image from the database to a file"""
    if not os.path.exists(DB_FILE):
        print(f"Database {DB_FILE} not found!")
        return
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT image_data FROM jail_records WHERE id = ?", (record_id,))
    result = cursor.fetchone()
    
    if result and result[0]:
        with open(output_filename, 'wb') as f:
            f.write(result[0])
        print(f"Image saved to {output_filename}")
    else:
        print(f"No image found for record ID {record_id}")
    
    conn.close()

def search_by_name(name):
    """Search for records by name"""
    if not os.path.exists(DB_FILE):
        print(f"Database {DB_FILE} not found!")
        return
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, first_name, middle_name, last_name, booking_date, 
               date_of_birth, gender, arrestor, charges, source_pdf
        FROM jail_records 
        WHERE first_name LIKE ? OR middle_name LIKE ? OR last_name LIKE ?
        ORDER BY booking_date
    """, (f"%{name}%", f"%{name}%", f"%{name}%"))
    
    records = cursor.fetchall()
    
    if records:
        print(f"Found {len(records)} records matching '{name}':\n")
        for record in records:
            id_num, first, middle, last, booking, dob, gender, arrestor, charges, source = record
            print(f"ID: {id_num}")
            print(f"Name: {first} {middle} {last}".strip())
            print(f"Booking: {booking}")
            print(f"DOB: {dob}")
            print(f"Gender: {gender}")
            print(f"Arrestor: {arrestor}")
            print(f"Charges: {charges}")
            print(f"Source: {source}")
            print("-" * 50)
    else:
        print(f"No records found matching '{name}'")
    
    conn.close()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "search" and len(sys.argv) > 2:
            search_by_name(sys.argv[2])
        elif sys.argv[1] == "image" and len(sys.argv) > 3:
            save_image_from_db(int(sys.argv[2]), sys.argv[3])
        else:
            print("Usage:")
            print("  python view_db.py                    # View all records")
            print("  python view_db.py search NAME        # Search by name")
            print("  python view_db.py image ID FILENAME  # Save image from record ID")
    else:
        view_database()
