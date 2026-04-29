from typing import Optional

from pydantic import BaseModel, Field, ConfigDict, model_validator

from fastapi import HTTPException

from pydantic.alias_generators import to_camel


from utils.schemas import BaseUserSchema, DetailUserSchema

class PhotoSchema(BaseModel):
    url: str


# class BaseUserSchema(BaseModel):
#     name: str
#     age: int | None = Field(default=None)
#     city: str | None = Field(default=None)
#     country: str | None = Field(default=None)
#     about: str | None = Field(default=None)
#     photos: list[PhotoSchema] | None = Field(default=None)
#     main_photo: PhotoSchema | None = Field(default=None)

#     model_config = ConfigDict(
#         alias_generator=to_camel,
#         populate_by_name=True,
#     )

#     @model_validator(mode="before")
#     @classmethod
#     def check_name(cls, data: dict):
#         if not data.get("name"):
#             raise HTTPException(
#                 status_code=400,
#                 detail="'email', 'name' or 'password' required field was missing"
#             )
#         return data


class LoginUserSchema(BaseModel):
    # email: str
    username: str
    password: str

    # @model_validator(mode="before")
    # @classmethod
    # def check_email_and_password(cls, data: dict):
    #     if not hasattr(data, 'email') or not hasattr(data, 'password'):
    #         raise HTTPException(
    #             status_code=400,
    #             detail="'email', 'name' or 'password' required field was missing"
    #         )
    #     return data


class RegisterUserSchema(BaseUserSchema, LoginUserSchema):
    pass


# class NewMessageNotificationSchema(BaseModel):
#     new_messages: bool


# class DetailUserSchema(BaseUserSchema):
#     # test
#     is_online: bool| None = Field(default=None)
#     is_premium: bool| None = Field(default=None)
#     is_vip: bool| None = Field(default=None)
#     #
#     is_new: bool | None = Field(default=None)
#     telegram_username: str | None = Field(default=None)
#     notifications: NewMessageNotificationSchema | None = Field(default=None)
#     created_at: str
#     updated_at: str


class RefreshToken(BaseModel):
    refresh_token: str



class RegisterEndpointResponse(BaseModel):
    user: DetailUserSchema
    token: str


class SendMessageSchema(BaseModel):
    account_id: int
    message_id: int
    text: Optional[str]


class SecretShcema(BaseModel):
    secret: str