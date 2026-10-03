from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query
)

from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Address
from app.schemas import (
    UserCreate,
    UserUpdate,
    UserResponse
)


router = APIRouter(
    prefix="/users",
    tags=["Users"]
)


# =========================================================
# CREATE USER
# POST /users/
# =========================================================

@router.post("/", response_model=UserResponse)
def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db)
):

    # Check duplicate email
    existing_user = (
        db.query(User)
        .filter(User.email == user_data.email)
        .first()
    )

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Email already exists"
        )

    # Create address
    new_address = Address(
        street=user_data.address.street,
        city=user_data.address.city,
        state=user_data.address.state,
        zip=user_data.address.zip
    )

    db.add(new_address)
    db.flush()

    # Create user
    new_user = User(
        name=user_data.name,
        email=user_data.email,
        age=user_data.age,
        gender=user_data.gender,
        address_id=new_address.id
    )

    db.add(new_user)

    db.commit()

    db.refresh(new_user)

    return new_user


# =========================================================
# GET ALL USERS
# GET /users/
# =========================================================

@router.get("/", response_model=list[UserResponse])
def get_users(
    db: Session = Depends(get_db)
):

    users = (
        db.query(User)
        .all()
    )

    return users


# =========================================================
# SEARCH USERS
# GET /users/search?name=john
# GET /users/search?email=gmail.com
# =========================================================

@router.get("/search", response_model=list[UserResponse])
def search_users(
    name: Optional[str] = None,
    email: Optional[str] = None,
    db: Session = Depends(get_db)
):

    query = db.query(User)

    if name:
        query = query.filter(
            User.name.ilike(f"%{name}%")
        )

    if email:
        query = query.filter(
            User.email.ilike(f"%{email}%")
        )

    return query.all()


# =========================================================
# FILTER USERS
#
# GET /users/filter?gender=Male
# GET /users/filter?age_min=20&age_max=30
# GET /users/filter?city=Dhaka
# =========================================================

@router.get("/filter", response_model=list[UserResponse])
def filter_users(
    gender: Optional[str] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    db: Session = Depends(get_db)
):

    query = db.query(User)

    # Filter gender
    if gender:
        query = query.filter(
            User.gender.ilike(gender)
        )

    # Minimum age
    if age_min is not None:
        query = query.filter(
            User.age >= age_min
        )

    # Maximum age
    if age_max is not None:
        query = query.filter(
            User.age <= age_max
        )

    if city or state:
        query = query.join(Address)

    # Filter city
    if city:
        query = query.filter(Address.city.ilike(city))

    # Filter state
    if state:
        query = query.filter(Address.state.ilike(state))

    return query.all()


# =========================================================
# GET USER DETAILS
# GET /users/{user_id}
# =========================================================

@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db)
):

    user = (
        db.query(User)
        .filter(User.id == user_id)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    return user


# =========================================================
# UPDATE USER
# PUT /users/{user_id}
# =========================================================

@router.put(
    "/{user_id}",
    response_model=UserResponse
)
def update_user(
    user_id: int,
    user_data: UserUpdate,
    db: Session = Depends(get_db)
):

    user = (
        db.query(User)
        .filter(User.id == user_id)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    # Update user fields
    if user_data.name is not None:
        user.name = user_data.name

    if user_data.email is not None:

        existing_email = (
            db.query(User)
            .filter(
                User.email == user_data.email,
                User.id != user_id
            )
            .first()
        )

        if existing_email:
            raise HTTPException(
                status_code=400,
                detail="Email already exists"
            )

        user.email = user_data.email

    if user_data.age is not None:
        user.age = user_data.age

    if user_data.gender is not None:
        user.gender = user_data.gender

    # Update address
    if user_data.address is not None:

        if user.address:

            user.address.street = (
                user_data.address.street
            )

            user.address.city = (
                user_data.address.city
            )

            user.address.state = (
                user_data.address.state
            )

            user.address.zip = (
                user_data.address.zip
            )

        else:

            new_address = Address(
                street=user_data.address.street,
                city=user_data.address.city,
                state=user_data.address.state,
                zip=user_data.address.zip
            )

            db.add(new_address)
            db.flush()

            user.address_id = new_address.id

    db.commit()

    db.refresh(user)

    return user


# =========================================================
# DELETE USER
# DELETE /users/{user_id}
# =========================================================

@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db)
):

    user = (
        db.query(User)
        .filter(User.id == user_id)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    address = user.address

    # Delete user
    db.delete(user)

    db.flush()

    # Delete address if no other user uses it
    if address:
        other_users = (
            db.query(User)
            .filter(
                User.address_id == address.id
            )
            .count()
        )

        if other_users == 0:
            db.delete(address)

    db.commit()

    return {
        "message": "User deleted successfully",
        "user_id": user_id
    }
