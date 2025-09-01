#!/usr/bin/env python3
import os
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time

BASE_URL = "https://apps.mesacounty.us/so-blotter-reports/"
NEW_FOLDER = "new"
ARCHIVE_FOLDER = "archive"

def get_existing_files():
    """Get list of existing files in new and archive folders"""
    existing_files = set()
    
    for folder in [NEW_FOLDER, ARCHIVE_FOLDER]:
        if os.path.exists(folder):
            for file in os.listdir(folder):
                if file.lower().endswith('.pdf'):
                    # Extract date from filename for comparison
                    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', file)
                    if date_match:
                        existing_files.add(date_match.group(1))
    
    return existing_files

def clean_folders():
    """Remove all existing PDF files to start fresh"""
    print("Cleaning existing files...")
    
    for folder in [NEW_FOLDER, ARCHIVE_FOLDER]:
        if os.path.exists(folder):
            for file in os.listdir(folder):
                if file.lower().endswith('.pdf'):
                    filepath = os.path.join(folder, file)
                    os.remove(filepath)
                    print(f"Removed: {file}")
    
    print("Folders cleaned!")

def download_file(url, filename):
    """Download a file from URL"""
    try:
        print(f"Downloading: {filename}")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        filepath = os.path.join(NEW_FOLDER, filename)
        with open(filepath, 'wb') as f:
            f.write(response.content)
        
        print(f"✓ Downloaded: {filename}")
        return True
    except Exception as e:
        print(f"✗ Failed to download {filename}: {e}")
        return False

def main():
    print("=== Mesa County Booking Report Gatherer (FRESH START) ===")
    
    # Ensure folders exist
    os.makedirs(NEW_FOLDER, exist_ok=True)
    os.makedirs(ARCHIVE_FOLDER, exist_ok=True)
    
    # Clean existing files to start fresh
    clean_folders()
    
    # Get existing files (should be empty now)
    existing_dates = get_existing_files()
    print(f"Found {len(existing_dates)} existing dates: {sorted(existing_dates)}")
    
    try:
        # Get the main page
        print(f"Fetching: {BASE_URL}")
        response = requests.get(BASE_URL, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all PDF links
        pdf_links = []
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.lower().endswith('.pdf') and 'booking' in href.lower():
                full_url = urljoin(BASE_URL, href)
                filename = os.path.basename(urlparse(full_url).path)
                pdf_links.append((full_url, filename))
        
        print(f"Found {len(pdf_links)} booking PDF links")
        
        downloaded = 0
        skipped = 0
        
        for url, filename in pdf_links:
            # Extract date from filename
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
            if date_match:
                file_date = date_match.group(1)
                
                if file_date in existing_dates:
                    print(f"⏭ Skipping {filename} (date {file_date} already exists)")
                    skipped += 1
                    continue
            
            # Download the file
            if download_file(url, filename):
                downloaded += 1
            else:
                skipped += 1
            
            # Small delay to be respectful
            time.sleep(1)
        
        print(f"\n=== Summary ===")
        print(f"Downloaded: {downloaded}")
        print(f"Skipped: {skipped}")
        print(f"Total processed: {downloaded + skipped}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
