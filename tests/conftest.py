from __future__ import annotations

import os
import sys
from pathlib import Path

import jwt
import pytest
from dotenv import load_dotenv


load_dotenv()



ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

jwtSecret = os.getenv("JWT_SECRET")

token = jwt.encode(
    {"sub": "my-client", "scopes": ["mcp:access"]},
    key=jwtSecret,
    algorithm="HS256",
)


@pytest.fixture(scope="session")
def auth_headers():
    """Returns HTTP headers with Bearer token for API calls"""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
