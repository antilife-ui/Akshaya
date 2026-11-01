from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ChatRequest, ChatResponse
from app.services import ai_chat

router = APIRouter(prefix="/ai", tags=["AI space"])


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest, db: Session = Depends(get_db)):
    return ai_chat.chat(db, body.session_id, body.message)


@router.get("/chat/{session_id}")
def chat_history(session_id: str, db: Session = Depends(get_db)):
    return ai_chat.history(db, session_id)
