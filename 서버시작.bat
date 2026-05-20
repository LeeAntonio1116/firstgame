@echo off
cd /d "e:\claude_workspace\firstgame"
.venv\Scripts\uvicorn main:app --reload
pause
