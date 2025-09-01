#!/bin/bash
mkdir -p new archive
pip3 install --user --break-system-packages PyMuPDF pdfplumber pillow requests
/opt/homebrew/bin/python3.12 -m pip install --user --break-system-packages PyMuPDF pdfplumber pillow requests
chmod +x run.py
