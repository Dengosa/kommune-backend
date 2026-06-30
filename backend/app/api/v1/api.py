from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import chat, waitlist, activation, vault, whatsapp, sms

api_router = APIRouter()

api_router.include_router(chat.router, tags=["chat"])
api_router.include_router(waitlist.router, tags=["waitlist"])
api_router.include_router(activation.router, tags=["activation"])
api_router.include_router(vault.router, tags=["vault"])
api_router.include_router(whatsapp.router, tags=["whatsapp"])
api_router.include_router(sms.router, tags=["sms"])
