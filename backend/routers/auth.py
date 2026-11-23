from fastapi import APIRouter, Depends, HTTPException, Response, Request
from sqlalchemy.orm import Session as DBSession

from backend.dependencies import get_db
from backend.services.audit_service import AuditService, client_ip
from backend.services.auth_service import AuthService, hash_password, verify_password
from backend.schemas.auth import ChangePasswordRequest, LoginRequest, UserResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


def get_auth_service(db: DBSession = Depends(get_db)) -> AuthService:
    return AuthService(db)


def get_current_user(request: Request, auth: AuthService = Depends(get_auth_service)):
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = auth.validate_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return user


@router.post("/login")
def login(
    data: LoginRequest,
    response: Response,
    request: Request,
    auth: AuthService = Depends(get_auth_service),
    db: DBSession = Depends(get_db),
):
    user = auth.authenticate(data.email, data.password)
    if not user:
        AuditService(db).record("auth.login_failed", user_email=data.email, ip_address=client_ip(request))
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = auth.create_session(user.id)
    AuditService(db).record("auth.login", user=user, ip_address=client_ip(request))
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/api",
        max_age=86400,  # 24 hours
    )
    return {"message": "Login successful"}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
    db: DBSession = Depends(get_db),
):
    token = request.cookies.get("session_token")
    if token:
        user = auth.validate_session(token)
        if user:
            AuditService(db).record("auth.logout", user=user, ip_address=client_ip(request))
        auth.delete_session(token)
    response.delete_cookie(
        "session_token",
        httponly=True,
        samesite="strict",
        secure=False,
        path="/api",
    )
    return {"message": "Logout successful"}


@router.get("/me", response_model=UserResponse)
def get_me(user=Depends(get_current_user)):
    return user


@router.post("/change-password")
def change_password(
    data: ChangePasswordRequest,
    request: Request,
    user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Change the current user's password.

    Requires the current password for verification.
    """
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(data.new_password)
    db.commit()
    AuditService(db).record(
        "auth.password_change", user=user, resource_type="user", resource_id=user.id,
        ip_address=client_ip(request),
    )
    return {"message": "Password changed successfully"}
