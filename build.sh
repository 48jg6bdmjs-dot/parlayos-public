#!/bin/bash
set -e
echo "Installing deps..."
pip install --break-system-packages -r requirements.txt || pip install -r requirements.txt
echo "Running engines..."
python run_all.py
echo "Build done - files:"
ls -lh parlayos.html index.html