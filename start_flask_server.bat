@echo off
echo Starting Flask Attention Server on port 5050...
cd /d "%~dp0attention_tracker"
python flask_server.py
pause
