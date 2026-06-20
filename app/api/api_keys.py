import secrets
import string
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import get_current_active_user, hash_api_key
from app.models import APIKey, Project, User, APIKeyStatus
from app.schemas import APIKeyCreate, APIKeyResponse, APIKeyCreateResponse, APIKeyUpdate

router = APIRouter(prefix="/api-keys", tags=["API Key"])


def generate_api_key() -> str:
    alphabet = string.ascii_letters + string.digits
    prefix = "sk_" + "".join(secrets.choice(alphabet) for _ in range(8))
    rest = "".join(secrets.choice(alphabet) for _ in range(32))
    return f"{prefix}_{rest}"


@router.post("", response_model=APIKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    key_data: APIKeyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    project = db.query(Project).filter(Project.id == key_data.project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != project.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    api_key = generate_api_key()
    key_prefix = api_key[:10]
    key_hash = hash_api_key(api_key)

    if key_data.expires_at and key_data.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expiration date must be in the future"
        )

    db_key = APIKey(
        project_id=key_data.project_id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=key_data.name,
        status=APIKeyStatus.ACTIVE,
        expires_at=key_data.expires_at
    )
    db.add(db_key)
    db.commit()
    db.refresh(db_key)

    return APIKeyCreateResponse(
        id=db_key.id,
        project_id=db_key.project_id,
        key_prefix=db_key.key_prefix,
        name=db_key.name,
        status=db_key.status,
        created_at=db_key.created_at,
        expires_at=db_key.expires_at,
        last_used_at=db_key.last_used_at,
        api_key=api_key
    )


@router.get("", response_model=List[APIKeyResponse])
async def get_api_keys(
    project_id: Optional[int] = None,
    status: Optional[APIKeyStatus] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    query = db.query(APIKey).join(Project)

    if current_user.tenant_id and not current_user.is_admin:
        query = query.filter(Project.tenant_id == current_user.tenant_id)
    elif project_id:
        query = query.filter(APIKey.project_id == project_id)

    if status:
        query = query.filter(APIKey.status == status)

    return query.offset(skip).limit(limit).all()


@router.get("/{key_id}", response_model=APIKeyResponse)
async def get_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    api_key = db.query(APIKey).filter(APIKey.id == key_id).first()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key not found"
        )

    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != api_key.project.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    return api_key


@router.put("/{key_id}", response_model=APIKeyResponse)
async def update_api_key(
    key_id: int,
    key_data: APIKeyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    api_key = db.query(APIKey).filter(APIKey.id == key_id).first()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key not found"
        )

    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != api_key.project.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    update_data = key_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(api_key, key, value)

    db.commit()
    db.refresh(api_key)
    return api_key


@router.post("/{key_id}/disable", response_model=APIKeyResponse)
async def disable_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    api_key = db.query(APIKey).filter(APIKey.id == key_id).first()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key not found"
        )

    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != api_key.project.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    api_key.status = APIKeyStatus.DISABLED
    db.commit()
    db.refresh(api_key)
    return api_key


@router.post("/{key_id}/enable", response_model=APIKeyResponse)
async def enable_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    api_key = db.query(APIKey).filter(APIKey.id == key_id).first()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key not found"
        )

    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != api_key.project.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    api_key.status = APIKeyStatus.ACTIVE
    db.commit()
    db.refresh(api_key)
    return api_key
