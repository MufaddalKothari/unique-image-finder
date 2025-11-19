#!/usr/bin/env bash
# quick_start.sh - create venv, install requirements and run the app (Linux / macOS)
set -e
if [ -d "unq_img" ]; then
  echo "Using existing virtualenv: unq_img"
else
  python3 -m venv unq_img
fi
source unq_img/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python main.py
