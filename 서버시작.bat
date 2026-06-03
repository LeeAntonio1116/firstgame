@echo off
cd e:\claude_workspace\firstgame
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
pause
