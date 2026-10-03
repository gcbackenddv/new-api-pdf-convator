from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey
)
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    age = Column(Integer)
    gender = Column(String)

    address_id = Column(
        Integer,
        ForeignKey("addresses.id")
    )

    address = relationship(
        "Address",
        back_populates="users"
    )


class Address(Base):
    __tablename__ = "addresses"

    id = Column(Integer, primary_key=True, index=True)
    street = Column(String)
    city = Column(String)
    state = Column(String)
    zip = Column(String)

    users = relationship(
        "User",
        back_populates="address"
    )
