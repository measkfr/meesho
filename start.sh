#!/bin/bash
cd /data/data/com.termux/files/home/Meesho-bot-main
exec python3 -m uvicorn app:app --host 127.0.0.1 --port 5000
