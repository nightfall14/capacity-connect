"""
Chat routes — real-time WebSocket + REST history.
Accessible to role in ('trainee', 'trainer').
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from threading import Lock

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import or_

from app.extensions import SessionLocal
from app.models import ChatMessage, ChatRoomRead, Course, Enrollment, User
from app.services.chat_manager import manager

router = APIRouter()

CHAT_ROLES = ("trainee", "trainer", "admin")

_presence_lock = Lock()
_online: Counter[int] = Counter()
_connections: dict[int, set[WebSocket]] = {}


def _guard(request: Request, db) -> User | None:
    from app.decorators import current_account

    user = current_account(request, db)
    if user and user.is_active and user.role in CHAT_ROLES:
        if user.role == "trainer" and not user.is_approved:
            return None
        return user
    return None


def _unread_summary(db, account: User) -> dict:
    private = (
        db.query(ChatMessage)
        .filter_by(recipient_id=account.id, room_type="private", read_at=None)
        .all()
    )
    by_sender = Counter(m.sender_id for m in private)
    marker = (
        db.query(ChatRoomRead)
        .filter_by(account_id=account.id, room_key="global")
        .first()
    )
    q = db.query(ChatMessage).filter_by(room_type="global")
    if marker:
        q = q.filter(ChatMessage.created_at > marker.last_read_at)
    return {"total": len(private) + q.count(), "global": q.count(), "private": dict(by_sender)}


def _chat_history(db, account_id: int, room_type: str, recipient_id: int | None):
    q = db.query(ChatMessage)
    if room_type == "global":
        return q.filter_by(room_type="global").order_by(ChatMessage.created_at.desc()).limit(100).all()[::-1]
    return q.filter(
        ChatMessage.room_type == "private",
        or_((ChatMessage.sender_id == account_id) & (ChatMessage.recipient_id == recipient_id),
            (ChatMessage.sender_id == recipient_id) & (ChatMessage.recipient_id == account_id)),
    ).order_by(ChatMessage.created_at.desc()).limit(100).all()[::-1]


def _mark_read(db, account: User, room_type: str, recipient_id: int | None) -> None:
    now = datetime.utcnow()
    if room_type == "global":
        marker = db.query(ChatRoomRead).filter_by(account_id=account.id, room_key="global").first()
        if marker:
            marker.last_read_at = now
        else:
            db.add(ChatRoomRead(account_id=account.id, room_key="global", last_read_at=now))
    elif recipient_id:
        db.query(ChatMessage).filter_by(
            recipient_id=account.id, sender_id=recipient_id, room_type="private", read_at=None
        ).update({"read_at": now})
    db.commit()


async def _broadcast(account_id: int, payload: dict) -> None:
    with _presence_lock:
        sockets = list(_connections.get(account_id, set()))
    for ws in sockets:
        try:
            await ws.send_json(payload)
        except Exception:
            pass


async def _broadcast_all(payload: dict) -> None:
    with _presence_lock:
        sockets = [
            socket
            for account_sockets in _connections.values()
            for socket in account_sockets
        ]
    for ws in sockets:
        try:
            await ws.send_json(payload)
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────────────

@router.get("", name="chat.chat_page")
async def chat_page(request: Request):
    from app import render

    with SessionLocal() as db:
        account = _guard(request, db)
        if not account:
            return RedirectResponse("/auth/login", status_code=303)

        recipient_id_str = request.query_params.get("recipient_id", "").strip()
        selected_recipient_id = int(recipient_id_str) if recipient_id_str.isdigit() else None

        participants = (
            db.query(User)
            .filter(
                User.id != account.id,
                User.role.in_(CHAT_ROLES),
                User.is_active.is_(True),
                or_(User.role != "trainer", User.is_approved.is_(True)),
            )
            .order_by(User.name)
            .all()
        )
        with _presence_lock:
            online = [k for k, v in _online.items() if v > 0]

        room_type = "private" if selected_recipient_id else "global"
        messages = _chat_history(db, account.id, room_type, selected_recipient_id)
        _mark_read(db, account, room_type, selected_recipient_id)
        unread = _unread_summary(db, account)

        return render(
            request, db, "chat.html",
            participants=participants, selected_recipient_id=selected_recipient_id,
            messages=messages, room_type=room_type, online_ids=online,
            unread=unread,
            unread_by_sender=unread["private"],
        )


@router.get("/history", name="chat.chat_history")
async def chat_history(request: Request):
    with SessionLocal() as db:
        account = _guard(request, db)
        if not account:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)

        room_type = request.query_params.get("room", "global")
        rid_str = request.query_params.get("recipient_id", "")
        recipient_id = int(rid_str) if rid_str.isdigit() else None
        messages = _chat_history(db, account.id, room_type, recipient_id)
        return JSONResponse({"messages": [m.to_dict() for m in messages]})


@router.get("/unread-count", name="chat.unread_count")
async def unread_count(request: Request):
    with SessionLocal() as db:
        account = _guard(request, db)
        if not account:
            return JSONResponse({"total": 0})
        return JSONResponse(_unread_summary(db, account))


@router.get("/online", name="chat.online_status")
async def online_status(request: Request):
    with _presence_lock:
        online = [k for k, v in _online.items() if v > 0]
    return JSONResponse({"online": online})


async def chat_ws(websocket: WebSocket):
    await websocket.accept()

    with SessionLocal() as db:
        account_id = websocket.session.get("account_id")
        account = db.get(User, account_id) if account_id else None
        if not account or not account.is_active or account.role not in CHAT_ROLES:
            await websocket.close(code=4001)
            return

    await manager.connect(websocket, account_id)
    with _presence_lock:
        _online[account_id] += 1
        _connections.setdefault(account_id, set()).add(websocket)

    try:
        await manager.broadcast({
            "type": "online_users_update",
            "online_users": await manager.online_user_ids(),
        })
        await manager.broadcast({
            "type": "online_count",
            "count": await manager.online_count(),
        })
        with SessionLocal() as db:
            unread = _unread_summary(db, account)
        await websocket.send_json({
            "type": "chat_ready",
            "data": {"unread": unread},
        })
        await _broadcast_all({
            "type": "presence_update",
            "data": {"account_id": account_id, "online": True},
        })
        while True:
            raw = await websocket.receive_json()
            message_type = raw.get("type", "send_message")

            if message_type == "peer_rescue_request":
                try:
                    course_id = int(raw.get("course_id"))
                except (TypeError, ValueError):
                    await websocket.send_json({
                        "type": "peer_rescue_failed",
                        "message": "A valid course is required.",
                    })
                    continue
                with SessionLocal() as db:
                    requester = db.get(User, account_id)
                    course = db.get(Course, course_id)
                    enrollment = (
                        db.query(Enrollment)
                        .filter(
                            Enrollment.course_id == course_id,
                            Enrollment.user_id == account_id,
                        )
                        .first()
                    )
                    if not requester or not course or not enrollment:
                        eligible_ids = []
                    else:
                        eligible_ids = [
                            user_id for (user_id,) in db.query(Enrollment.user_id)
                            .filter(
                                Enrollment.course_id == course_id,
                                Enrollment.user_id != account_id,
                                Enrollment.progress_percentage > (enrollment.progress_percentage or 0),
                                Enrollment.status.in_(("active", "Enrolled", "in progress", "In Progress", "Completed")),
                            )
                            .all()
                        ]
                online_ids = set(await manager.online_user_ids())
                eligible_ids = [user_id for user_id in eligible_ids if user_id in online_ids]
                if not eligible_ids:
                    await websocket.send_json({
                        "type": "peer_rescue_failed",
                        "message": "No available peers online with higher progress.",
                    })
                    continue
                target_id = eligible_ids[0]
                await manager.send_to_user(target_id, {
                    "type": "incoming_peer_rescue",
                    "requester_id": account_id,
                    "requester_name": account.name,
                    "course_id": course_id,
                    "course_name": course.title,
                })
                await websocket.send_json({
                    "type": "peer_rescue_pending",
                    "message": "Request sent to an available peer.",
                })
                continue

            if message_type == "peer_rescue_accept":
                try:
                    requester_id = int(raw.get("requester_id"))
                except (TypeError, ValueError):
                    continue
                await manager.send_to_user(requester_id, {
                    "type": "peer_rescue_accepted",
                    "helper_id": account_id,
                    "helper_name": account.name,
                    "message": f"{account.name} accepted your Peer Rescue request.",
                })
                continue

            if message_type == "join_global":
                with SessionLocal() as db:
                    history = _chat_history(db, account_id, "global", None)
                    history_payload = [message.to_dict() for message in history]
                await websocket.send_json({
                    "type": "history",
                    "data": {
                        "room_type": "global",
                        "recipient_id": None,
                        "messages": history_payload,
                    },
                })
                continue

            if message_type == "send_global_message" or (
                "message" in raw and "body" not in raw and "type" not in raw
            ):
                text = str(raw.get("message", "")).strip()
                if not text or len(text) > 2000:
                    continue
                is_anonymous = bool(raw.get("is_anonymous", False))
                display_name = "Anonymous User" if is_anonymous else account.name
                display_role = "Hidden" if is_anonymous else account.role.title()
                timestamp = datetime.utcnow().strftime("%H:%M")
                with SessionLocal() as db:
                    message = ChatMessage(
                        sender_id=account.id,
                        room_type="global",
                        body=text,
                        is_anonymous=is_anonymous,
                    )
                    db.add(message)
                    db.commit()
                await manager.broadcast({
                    "type": "message",
                    "user": display_name,
                    "role": display_role,
                    "message": text,
                    "timestamp": timestamp,
                    "is_anonymous": is_anonymous,
                    "user_id": account.id,
                })
                continue

            if message_type == "request_history":
                room_type = raw.get("room_type", "global")
                recipient_id = raw.get("recipient_id")
                with SessionLocal() as db:
                    history = _chat_history(db, account_id, room_type, recipient_id)
                    history_payload = [message.to_dict() for message in history]
                await websocket.send_json({
                    "type": "history",
                    "data": {
                        "room_type": room_type,
                        "recipient_id": recipient_id,
                        "messages": history_payload,
                    },
                })
                continue

            if message_type == "mark_read":
                room_type = raw.get("room_type", "global")
                recipient_id = raw.get("recipient_id")
                with SessionLocal() as db:
                    account = db.get(User, account_id)
                    if account:
                        _mark_read(db, account, room_type, recipient_id)
                continue

            # Keep the existing private-chat protocol available on /chat/ws.
            from app.schemas import ChatMessageModel
            try:
                data = ChatMessageModel(**raw)
            except Exception:
                continue

            with SessionLocal() as db:
                sender = db.get(User, account_id)
                if not sender:
                    continue

                if data.room_type == "private" and data.recipient_id:
                    recipient = db.get(User, data.recipient_id)
                    if not recipient or recipient.role not in CHAT_ROLES:
                        continue
                    msg = ChatMessage(
                        sender_id=sender.id, recipient_id=data.recipient_id,
                        room_type="private", body=data.body,
                        is_anonymous=False,
                    )
                else:
                    msg = ChatMessage(
                        sender_id=sender.id, room_type="global",
                        body=data.body,
                        is_anonymous=data.anonymous or data.is_anonymous,
                    )
                db.add(msg)
                db.commit()
                payload = msg.to_dict()

            event = {"type": "new_message", "data": payload}
            if data.room_type == "global":
                await _broadcast_all(event)
            else:
                await _broadcast(account_id, event)
                if data.recipient_id:
                    await _broadcast(data.recipient_id, event)

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)
        with _presence_lock:
            _online[account_id] = max(0, _online[account_id] - 1)
            _connections.get(account_id, set()).discard(websocket)
            still_online = _online.get(account_id, 0) > 0
        if not still_online:
            await _broadcast_all({
                "type": "presence_update",
                "data": {"account_id": account_id, "online": False},
            })
        await manager.broadcast({
            "type": "online_count",
            "count": await manager.online_count(),
        })
        await manager.broadcast({
            "type": "online_users_update",
            "online_users": await manager.online_user_ids(),
        })


@router.websocket("/ws")
async def chat_ws_compat(websocket: WebSocket):
    await chat_ws(websocket)


@router.websocket("/ws/chat")
async def chat_ws_prefixed(websocket: WebSocket):
    await chat_ws(websocket)
