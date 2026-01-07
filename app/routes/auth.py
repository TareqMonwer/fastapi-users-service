import logging
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime

from app.database import get_db
from app.schemas.auth import (
    UserRegister,
    UserLogin,
    TokenResponse,
    RefreshTokenRequest,
    OpaqueTokenRequest,
    OpaqueTokenResponse,
)
from app.schemas.user import User
from app.crud.user import UserCRUD
from app.crud.auth import RefreshTokenCRUD
from app.crud.opaque_token import OpaqueTokenCRUD
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
)
from app.core.constants import TOKEN_TYPE_REFRESH, ERROR_INVALID_CREDENTIALS
from app.exceptions.auth_exceptions import (
    InvalidCredentialsException,
    InvalidRefreshTokenException,
)
from app.exceptions.custom_exceptions import UserAlreadyExistsException
from app.models.users import User as UserModel
from app.middleware.metrics_middleware import AUTH_TOKENS_ISSUED_TOTAL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/register", response_model=User, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserRegister,
    db: Session = Depends(get_db)
):
    """Register a new user."""
    try:
        logger.info(f"Registration attempt for email: {user_data.email}")
        
        # Check if user already exists
        existing_user = UserCRUD.get_user_by_email(db, user_data.email)
        if existing_user:
            logger.warning(f"Registration failed: email {user_data.email} already exists")
            raise UserAlreadyExistsException(user_data.email)
        
        # Hash password
        password_hash = hash_password(user_data.password)
        
        # Create user
        from app.schemas.user import UserCreate
        user_create = UserCreate(
            name=user_data.name,
            email=user_data.email,
            phone=user_data.phone,
            password=user_data.password
        )
        
        db_user = UserCRUD.create_user(db, user_create, password_hash)
        logger.info(f"User registered successfully with ID: {db_user.id}")
        
        return db_user
    
    except UserAlreadyExistsException:
        raise
    except Exception as e:
        logger.error(f"Error during registration: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        )


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: UserLogin,
    db: Session = Depends(get_db)
):
    """Authenticate user and return access and refresh tokens."""
    try:
        logger.info(f"Login attempt for email: {credentials.email}")
        
        # Get user by email
        user = UserCRUD.get_user_by_email(db, credentials.email)
        if not user:
            logger.warning(f"Login failed: user with email {credentials.email} not found")
            raise InvalidCredentialsException()
        
        # Verify password
        if not verify_password(credentials.password, user.password_hash):
            logger.warning(f"Login failed: invalid password for email {credentials.email}")
            raise InvalidCredentialsException()
        
        # Create tokens
        token_data = {"sub": str(user.id), "email": user.email}
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)
        
        # Store refresh token in database
        RefreshTokenCRUD.create_refresh_token(db, user.id, refresh_token)
        
        # Increment metrics
        AUTH_TOKENS_ISSUED_TOTAL.labels(token_type="access", endpoint="login").inc()
        AUTH_TOKENS_ISSUED_TOTAL.labels(token_type="refresh", endpoint="login").inc()
        
        logger.info(f"User {user.id} logged in successfully")
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer"
        )
    
    except (InvalidCredentialsException, HTTPException):
        raise
    except Exception as e:
        logger.error(f"Error during login: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login failed: {str(e)}"
        )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    token_request: RefreshTokenRequest,
    db: Session = Depends(get_db)
):
    """Refresh access token using refresh token."""
    try:
        logger.info("Token refresh attempt")
        
        # Decode refresh token
        try:
            payload = decode_token(token_request.refresh_token)
        except HTTPException:
            logger.warning("Token refresh failed: invalid token")
            raise InvalidRefreshTokenException()
        
        # Verify token type
        token_type = payload.get("type")
        if token_type != TOKEN_TYPE_REFRESH:
            logger.warning("Token refresh failed: wrong token type")
            raise InvalidRefreshTokenException()
        
        # Verify token exists in database and is not revoked
        db_refresh_token = RefreshTokenCRUD.get_refresh_token(
            db,
            token_request.refresh_token
        )
        if not db_refresh_token:
            logger.warning("Token refresh failed: token not found or revoked")
            raise InvalidRefreshTokenException()
        
        # Check if token is expired
        if db_refresh_token.expires_at < datetime.utcnow():
            logger.warning("Token refresh failed: token expired")
            RefreshTokenCRUD.revoke_refresh_token(db, token_request.refresh_token)
            raise InvalidRefreshTokenException()
        
        # Get user
        user_id = payload.get("sub")
        user = UserCRUD.get_user(db, user_id)
        if not user:
            logger.warning(f"Token refresh failed: user {user_id} not found or inactive")
            raise InvalidRefreshTokenException()
        
        # Create new tokens
        token_data = {"sub": str(user.id), "email": user.email}
        new_access_token = create_access_token(token_data)
        new_refresh_token = create_refresh_token(token_data)
        
        # Revoke old refresh token and create new one
        RefreshTokenCRUD.revoke_refresh_token(db, token_request.refresh_token)
        RefreshTokenCRUD.create_refresh_token(db, user.id, new_refresh_token)
        
        # Increment metrics
        AUTH_TOKENS_ISSUED_TOTAL.labels(token_type="access", endpoint="refresh").inc()
        AUTH_TOKENS_ISSUED_TOTAL.labels(token_type="refresh", endpoint="refresh").inc()
        
        logger.info(f"Token refreshed successfully for user {user.id}")
        
        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer"
        )
    
    except (InvalidRefreshTokenException, HTTPException):
        raise
    except Exception as e:
        logger.error(f"Error during token refresh: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Token refresh failed: {str(e)}"
        )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    token_request: RefreshTokenRequest,
    db: Session = Depends(get_db)
):
    """Logout user by revoking refresh token."""
    try:
        logger.info("Logout attempt")
        
        # Revoke refresh token
        success = RefreshTokenCRUD.revoke_refresh_token(db, token_request.refresh_token)
        
        if success:
            logger.info("User logged out successfully")
        else:
            logger.warning("Logout: refresh token not found")
        
        return None
    
    except Exception as e:
        logger.error(f"Error during logout: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Logout failed: {str(e)}"
        )


@router.get("/me", response_model=User)
async def get_current_user_info(
    current_user: UserModel = Depends(get_current_user)
):
    """Get current authenticated user information."""
    return current_user


@router.post("/login-opaque", response_model=OpaqueTokenResponse)
async def login_opaque(
    credentials: UserLogin,
    db: Session = Depends(get_db)
):
    """Authenticate user and return opaque access and refresh tokens."""
    try:
        logger.info(f"Opaque token login attempt for email: {credentials.email}")
        
        # Get user by email
        user = UserCRUD.get_user_by_email(db, credentials.email)
        if not user:
            logger.warning(f"Opaque login failed: user with email {credentials.email} not found")
            raise InvalidCredentialsException()
        
        # Verify password
        if not verify_password(credentials.password, user.password_hash):
            logger.warning(f"Opaque login failed: invalid password for email {credentials.email}")
            raise InvalidCredentialsException()
        
        # Create opaque tokens
        access_token_obj = OpaqueTokenCRUD.create_opaque_token(db, user.id, token_type="access")
        refresh_token_obj = OpaqueTokenCRUD.create_opaque_token(db, user.id, token_type="refresh")
        
        # Increment metrics
        AUTH_TOKENS_ISSUED_TOTAL.labels(token_type="opaque_access", endpoint="login-opaque").inc()
        AUTH_TOKENS_ISSUED_TOTAL.labels(token_type="opaque_refresh", endpoint="login-opaque").inc()
        
        logger.info(f"User {user.id} logged in successfully with opaque tokens")
        
        return OpaqueTokenResponse(
            access_token=access_token_obj.token,
            refresh_token=refresh_token_obj.token,
            token_type="bearer"
        )
    
    except (InvalidCredentialsException, HTTPException):
        raise
    except Exception as e:
        logger.error(f"Error during opaque login: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Opaque login failed: {str(e)}"
        )


@router.post("/validate-opaque")
async def validate_opaque_token(
    token_request: OpaqueTokenRequest,
    db: Session = Depends(get_db)
):
    """Validate an opaque token and return user information."""
    try:
        logger.info("Opaque token validation attempt")
        
        # Validate token
        db_token = OpaqueTokenCRUD.validate_opaque_token(db, token_request.token)
        if not db_token:
            logger.warning("Opaque token validation failed: invalid or expired token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired opaque token"
            )
        
        # Get user
        user = UserCRUD.get_user(db, db_token.user_id)
        if not user:
            logger.warning(f"Opaque token validation failed: user {db_token.user_id} not found")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        
        logger.info(f"Opaque token validated successfully for user {user.id}")
        
        return {
            "valid": True,
            "user_id": user.id,
            "email": user.email,
            "token_type": db_token.token_type,
            "expires_at": db_token.expires_at.isoformat()
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during opaque token validation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Token validation failed: {str(e)}"
        )


@router.post("/refresh-opaque", response_model=OpaqueTokenResponse)
async def refresh_opaque_token(
    token_request: OpaqueTokenRequest,
    db: Session = Depends(get_db)
):
    """Refresh opaque access token using opaque refresh token."""
    try:
        logger.info("Opaque token refresh attempt")
        
        # Validate refresh token
        db_refresh_token = OpaqueTokenCRUD.validate_opaque_token(
            db, token_request.token, token_type="refresh"
        )
        if not db_refresh_token:
            logger.warning("Opaque token refresh failed: invalid or expired refresh token")
            raise InvalidRefreshTokenException()
        
        # Get user
        user = UserCRUD.get_user(db, db_refresh_token.user_id)
        if not user:
            logger.warning(f"Opaque token refresh failed: user {db_refresh_token.user_id} not found")
            raise InvalidRefreshTokenException()
        
        # Revoke old refresh token and create new tokens
        OpaqueTokenCRUD.revoke_opaque_token(db, db_refresh_token.token)
        new_access_token_obj = OpaqueTokenCRUD.create_opaque_token(db, user.id, token_type="access")
        new_refresh_token_obj = OpaqueTokenCRUD.create_opaque_token(db, user.id, token_type="refresh")
        
        # Increment metrics
        AUTH_TOKENS_ISSUED_TOTAL.labels(token_type="opaque_access", endpoint="refresh-opaque").inc()
        AUTH_TOKENS_ISSUED_TOTAL.labels(token_type="opaque_refresh", endpoint="refresh-opaque").inc()
        
        logger.info(f"Opaque tokens refreshed successfully for user {user.id}")
        
        return OpaqueTokenResponse(
            access_token=new_access_token_obj.token,
            refresh_token=new_refresh_token_obj.token,
            token_type="bearer"
        )
    
    except (InvalidRefreshTokenException, HTTPException):
        raise
    except Exception as e:
        logger.error(f"Error during opaque token refresh: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Token refresh failed: {str(e)}"
        )


@router.post("/logout-opaque", status_code=status.HTTP_204_NO_CONTENT)
async def logout_opaque(
    token_request: OpaqueTokenRequest,
    db: Session = Depends(get_db)
):
    """Logout user by revoking opaque token."""
    try:
        logger.info("Opaque token logout attempt")
        
        # Revoke token
        success = OpaqueTokenCRUD.revoke_opaque_token(db, token_request.token)
        
        if success:
            logger.info("User logged out successfully (opaque token)")
        else:
            logger.warning("Logout: opaque token not found")
        
        return None
    
    except Exception as e:
        logger.error(f"Error during opaque logout: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Logout failed: {str(e)}"
        )
