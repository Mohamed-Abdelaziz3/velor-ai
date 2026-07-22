from fastapi import Depends, Request, HTTPException
import os
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from database import Company, get_db

JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"


def get_current_user(request: Request, db: Session = Depends(get_db)) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Token missing or expired")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("token_type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        cid: str = payload.get("company_id", "")
        if not cid:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        company = db.query(Company).filter(
            Company.company_id == cid,
            Company.is_deleted == False,
        ).first()
        if not company:
            raise HTTPException(status_code=401, detail="Account is unavailable")
        return {"company_id": company.company_id, "role": company.role}
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalid or expired")
