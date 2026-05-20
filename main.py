from fastapi import FastAPI
from routers import auth, character, blacksmith, command, admin

app = FastAPI()
app.include_router(auth.router)
app.include_router(character.router)
app.include_router(blacksmith.router)
app.include_router(command.router)
app.include_router(admin.router)
