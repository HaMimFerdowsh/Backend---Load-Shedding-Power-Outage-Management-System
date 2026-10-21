import os
from datetime import timedelta, datetime, timezone
from typing import Annotated, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from jose import jwt, JWTError
from passlib.context import CryptContext
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Users, Areas

router = APIRouter()

bcrypt_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
OAuth2_bearer = OAuth2PasswordBearer(tokenUrl='login')

# Create your own key:  python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY = os.getenv('SECRET_KEY', 'dev-only-change-me')
ALGORITHM = 'HS256'

ACCESS_MINUTES = 30
REFRESH_DAYS = 7
RESET_MINUTES = 15

# No email service yet, so the reset token is returned in the response for testing.
# Set to False when you finish.
DEBUG = True


class CreateUsers(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=30)
    firstname: str = Field(min_length=1, max_length=50)
    lastname: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=64)
    role: Literal['admin', 'user'] = 'user'
    area_id: Optional[int] = None


class UpdateUser(BaseModel):
    email: Optional[EmailStr] = Field(default=None)
    username: Optional[str] = Field(default=None, min_length=3, max_length=30)
    firstname: Optional[str] = Field(default=None, min_length=1, max_length=50)
    lastname: Optional[str] = Field(default=None, min_length=1, max_length=50)
    area_id: Optional[int] = Field(default=None)


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPassword(BaseModel):
    email: EmailStr


class ResetPassword(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=64)

class ChangePassword(BaseModel):
    old_password: str = Field(min_length=1, max_length=64)
    new_password: str = Field(min_length=8, max_length=64)


def authenticate_user(username, password, db):
    user = db.query(Users).filter(Users.username == username).first()
    if user is None:
        return False
    if bcrypt_context.verify(password, user.hash_password):
        return user
    return False


def create_token(username: str, user_id: int, role: str, token_type: str, expires_delta: timedelta):
    encode = {'sub': username, 'id': user_id, 'role': role, 'type': token_type}
    encode.update({'exp': datetime.now(timezone.utc) + expires_delta})
    return jwt.encode(encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str, expected_type: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        # bad signature or expired
        raise HTTPException(status_code=401, detail='Token invalid or expired')
    if payload.get('type') != expected_type:
        raise HTTPException(status_code=401, detail='Wrong token type')
    return payload


def get_current_user(token: Annotated[str, Depends(OAuth2_bearer)]):
    payload = decode_token(token, 'access')
    username = payload.get('sub')
    user_id = payload.get('id')
    if username is None or user_id is None:
        raise HTTPException(status_code=401, detail='Could not validate user')
    return {'username': username, 'id': user_id, 'role': payload.get('role')}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]


def admin_only(user: user_dependency):
    if user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail='Admin access required')
    return user


admin_dependency = Annotated[dict, Depends(admin_only)]


# ---------------------------------------------------------------
# Signup / Login / Refresh
# ---------------------------------------------------------------
@router.post('/signup')
def create_users(db: db_dependency, new_user: CreateUsers):

    if db.query(Users).filter(Users.email == new_user.email).first():
        raise HTTPException(status_code=400, detail='Email already registered')
    if db.query(Users).filter(Users.username == new_user.username).first():
        raise HTTPException(status_code=400, detail='Username already taken')
    if new_user.area_id and db.query(Areas).filter(Areas.id == new_user.area_id).first() is None:
        raise HTTPException(status_code=404, detail='Area Not Found')

    user_model = Users(
        email=new_user.email,
        username=new_user.username,
        firstname=new_user.firstname,
        lastname=new_user.lastname,
        hash_password=bcrypt_context.hash(new_user.password),
        is_active=True,
        role=new_user.role,
        area_id=new_user.area_id,
    )

    db.add(user_model)
    db.commit()

    return JSONResponse(status_code=201, content={'message': 'User created successfully'})


@router.post('/login')
def login_user(db: db_dependency, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):

    user = authenticate_user(form_data.username, form_data.password, db)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid username or password')
    if not user.is_active:
        raise HTTPException(status_code=403, detail='Account is deactivated')

    return {
        'access_token': create_token(user.username, user.id, user.role, 'access', timedelta(minutes=ACCESS_MINUTES)),
        'refresh_token': create_token(user.username, user.id, user.role, 'refresh', timedelta(days=REFRESH_DAYS)),
        'token_type': 'bearer',
    }


@router.post('/refresh')
def refresh_access_token(db: db_dependency, body: RefreshRequest):

    payload = decode_token(body.refresh_token, 'refresh')

    user = db.query(Users).filter(Users.id == payload.get('id')).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail='User not available')

    return {
        'access_token': create_token(user.username, user.id, user.role, 'access', timedelta(minutes=ACCESS_MINUTES)),
        'token_type': 'bearer',
    }


# ---------------------------------------------------------------
# Forgot / Reset password
# ---------------------------------------------------------------
@router.post('/forgot-password')
def forgot_password(db: db_dependency, body: ForgotPassword):

    user = db.query(Users).filter(Users.email == body.email).first()
    response = {'message': 'If this email is registered, a reset link has been sent'}

    if user:
        token = create_token(user.username, user.id, user.role, 'reset', timedelta(minutes=RESET_MINUTES))
        print(f'[RESET TOKEN] {token}')      # TODO: send by email
        if DEBUG:
            response['reset_token'] = token

    return response

@router.put('/change-password')
def change_password(user: user_dependency, db: db_dependency, body: ChangePassword):

    current_user = db.query(Users).filter(Users.id == user.get('id')).first()
    if current_user is None:
        raise HTTPException(status_code=404, detail='User not found')

    if not bcrypt_context.verify(body.old_password, current_user.hash_password):
        raise HTTPException(status_code=400, detail='Old password is incorrect')

    if body.old_password == body.new_password:
        raise HTTPException(status_code=400, detail='New password must be different from old password')

    current_user.hash_password = bcrypt_context.hash(body.new_password)
    db.commit()
    return JSONResponse(status_code=200, content={'message': 'Password changed successfully'})


@router.post('/reset-password')
def reset_password(db: db_dependency, body: ResetPassword):

    payload = decode_token(body.token, 'reset')

    user = db.query(Users).filter(Users.id == payload.get('id')).first()
    if user is None:
        raise HTTPException(status_code=404, detail='User not found')

    user.hash_password = bcrypt_context.hash(body.new_password)
    db.commit()
    return JSONResponse(status_code=200, content={'message': 'Password reset successfully'})


# ---------------------------------------------------------------
# Profile (read / update / delete)
# ---------------------------------------------------------------
@router.get('/user')
def get_user_details(user: user_dependency, db: db_dependency):

    current_user = db.query(Users).filter(Users.id == user.get('id')).first()
    if current_user is None:
        raise HTTPException(status_code=404, detail='User not found')

    return {
        'id': current_user.id,
        'email': current_user.email,
        'username': current_user.username,
        'firstname': current_user.firstname,
        'lastname': current_user.lastname,
        'area_id': current_user.area_id,
        'role': current_user.role,
        'is_active': current_user.is_active,
    }


@router.put('/edituser')
def update_user(user: user_dependency, db: db_dependency, update_user: UpdateUser):

    current_user = db.query(Users).filter(Users.id == user.get('id')).first()
    if current_user is None:
        raise HTTPException(status_code=404, detail='User not found')

    update_data = update_user.model_dump(exclude_unset=True)

    if 'email' in update_data and update_data['email'] != current_user.email:
        if db.query(Users).filter(Users.email == update_data['email']).first():
            raise HTTPException(status_code=400, detail='Email already registered')
    if 'username' in update_data and update_data['username'] != current_user.username:
        if db.query(Users).filter(Users.username == update_data['username']).first():
            raise HTTPException(status_code=400, detail='Username already taken')
    if update_data.get('area_id') and db.query(Areas).filter(Areas.id == update_data['area_id']).first() is None:
        raise HTTPException(status_code=404, detail='Area Not Found')

    for key, value in update_data.items():
        setattr(current_user, key, value)

    db.commit()
    return JSONResponse(status_code=200, content={'message': 'User updated successfully'})


@router.delete('/deleteuser')
def delete_user(user: user_dependency, db: db_dependency):

    current_user = db.query(Users).filter(Users.id == user.get('id')).first()
    if current_user is None:
        raise HTTPException(status_code=404, detail='User not found')

    db.delete(current_user)
    db.commit()
    return JSONResponse(status_code=200, content={'message': 'User deleted successfully'})