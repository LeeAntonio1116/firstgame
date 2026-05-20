from dotenv import load_dotenv
import os

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
JWT_SECRET = os.getenv("JWT_SECRET")
INVITE_CODE = os.getenv("INVITE_CODE", "2580")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 7
