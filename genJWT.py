import jwt
import os
from dotenv import load_dotenv

load_dotenv()

token = jwt.encode(
    {"sub": "my-client", "scopes": ["mcp:access"]},
    key=os.getenv("JWT_SECRET"),
    algorithm="HS256",
)
print(token)
