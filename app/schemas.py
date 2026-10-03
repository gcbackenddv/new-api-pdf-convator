from pydantic import BaseModel, ConfigDict, Field
from typing import Optional


class AddressBase(BaseModel):
    street: str
    city: str
    state: str
    zip: str

class AddressCreate(AddressBase):
    pass

class AddressResponse(AddressBase):
    id: int

    model_config = ConfigDict(from_attributes=True)

class UserBase(BaseModel):
    name: str
    email: str
    age: Optional[int] = None
    gender: Optional[str] = None

class UserCreate(UserBase):
    address: AddressCreate


class UserUpdate(UserBase):
    name: Optional[str] = None
    email: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    address: Optional[AddressCreate] = None



class UserResponse(UserBase):
    id: int
    address: Optional[AddressResponse] = None

    model_config = ConfigDict(from_attributes=True)
