from datetime import datetime

from typing import Optional, Literal

# from enum import Enum

from pydantic import BaseModel, Field, ConfigDict, model_validator

from fastapi import HTTPException

from pydantic.alias_generators import to_camel

from utils.enums import MessageStatusEnum, MessageTypeEnum, ThreadColorEnum



# class MessageTypeEnum(str, Enum):
#     TEXT = "text"
#     VIDEO = "video"
#     PHOTO = "photo"
#     AUDIO = "audio"
#     AUDIOMESSAGE = "audiomessage"
#     VIDEOMESSAGE = "videomessage"


# class MessageStatusEnum(str, Enum):
#     SENT = "sent"
#     DELIVERED = "delivered"
#     READ = "read"


class PhotoSchema(BaseModel):
    url: str


class BaseUserSchema(BaseModel):
    name: str
    age: int | None = Field(default=None)
    city: str | None = Field(default=None)
    country: str | None = Field(default=None)
    about: str | None = Field(default=None)
    photos: list[PhotoSchema] | None = Field(default=None)
    main_photo: PhotoSchema | None = Field(default=None)

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class UpdateUserSchema(BaseModel):
    name: Optional[str] = None
    age: Optional[int] = None
    city: Optional[str] = None
    country: Optional[str] = None
    about: Optional[str] = None
    # photos: list[PhotoSchema] | None = Field(default=None)
    # main_photo: PhotoSchema | None = Field(default=None)

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class NotificationsSchema(BaseModel):
    message_notifications: bool = Field(alias='newMessages')

    model_config = ConfigDict(
        populate_by_name=True,
        serialize_by_alias=True
    )


class DetailUserSchema(BaseUserSchema):
    id: int
    # test
    is_online: bool| None = Field(default=None)
    is_premium: bool| None = Field(default=None)
    is_vip: bool| None = Field(default=None)
    #
    is_new: bool | None = Field(default=None)
    telegram_username: str | None = Field(default=None)
    notifications: NotificationsSchema | None = Field(default=None)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BaseChatSchema(BaseModel):
    id: int
    # participants: list[DetailUserSchema] = Field(validation_alias='users')
    # participants: list[int]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class BaseParticipantSchema(BaseModel):
    id: int
    name: str
    photo: str | None = Field(default=None)
    is_online: bool = Field(default=True)

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class DetailViewChatSchema(BaseChatSchema):
    participants: list[int]


class ListVeiwChatSchema(BaseChatSchema):
    participant: Optional[BaseParticipantSchema] | None = Field(default=None)


class BaseMessageSchema(BaseModel):
    text: str
    type: MessageTypeEnum = Field(default=MessageTypeEnum.TEXT)
    reply_to_id: int | None = Field(default=None)

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class AddMessageSchema(BaseMessageSchema):
    pass


class DetailMessageSchema(BaseMessageSchema):
    id: int
    chat_id: int
    sender_id: int
    created_at: datetime
    updated_at: datetime
    reactions: str | None = Field(default=None)
    is_read: bool = Field(default=False)
    status: MessageStatusEnum = Field(default=MessageStatusEnum.APPROVED)




class CreateAccountSchema(BaseModel):
    username: str
    password: str



class CreateMessageSchema(BaseModel):
    message_type: Literal['text', 'photo', 'video', 'audio']
    account_id: int
    text: str
    thread_id: str
    attachment: Optional[dict]


class AccountThread(BaseModel):
    id: str
    thread_id: str
    guest_id: int
    guest_username: str
    last_activity: str
    pending_msgs: int


class AccountSchema(BaseModel):
    id: str
    username: str
    insta_id: str
    is_active: str
    created_at: datetime
    updated_at: datetime
    threads: list[AccountThread]


class NewAccountSchema(BaseModel):
    id: int
    username: str
    view_name: str | None
    fullname: str | None = Field(default=None)
    # insta_id: str
    created_at: datetime
    updated_at: datetime
    photo_url: str | None = Field(default=None)
    is_active: bool
    thread_count: int
    has_unread: bool
    has_error: bool
    information: str | None = Field(default=None)
    folder_id: str | None
    profile_id: str | None


class PatchAccountSchema(BaseModel):
    account_id: int
    is_active: bool


class PatchInformationAccountSchema(BaseModel):
    account_id: int
    information: str


class PatchPhotoAccountSchema(BaseModel):
    account_id: int
    media_url: str


class PatchViewNameAccountSchema(BaseModel):
    account_id: int
    view_name: str


class ThreadSchema(BaseModel):
    id: int
    account_name: str
    user_name: str
    has_unread: bool
    last_activity: str
    color_level: str


class EditThreadColorLevelSchema(BaseModel):
    thread_id: int
    color_level: ThreadColorEnum


class EditThreadUnreadMarkSchema(BaseModel):
    thread_id: int


class EditThreadNotesSchema(BaseModel):
    thread_id: int
    notes: str | None


class AttachmentSchema(BaseModel):
    media_type: str
    media_url: str


class MessageSchema(BaseModel):
    id: int
    role: str
    content: str
    translated_content: str | None = Field(default=None)
    ts: str
    modStatus: str
    attachments: list[AttachmentSchema] | None




class AccountInformationSchema(BaseModel):
    photo_url: str | None
    information: str | None
    username: str | None = Field(default=None)
    full_name: str | None = Field(default=None)
    account_id: int


class UserInformationSchema(BaseModel):
    photo_url: str | None
    information: dict | None
    insta_link: str | None
    username: str | None = Field(default=None)
    full_name: str | None = Field(default=None)


#
class DetailThreadSchema(BaseModel):
    thread_name: str
    message_count: int
    account_information: AccountInformationSchema | None
    user_information: UserInformationSchema | None
    context: str | None
    notes: str | None
    messages: list[MessageSchema]


class UpdateProfileDataSchema(BaseModel):
    account_id: int
    folder_id: str
    profile_id: str
# class DetailThreadSchema(BaseModel):
#     thread_name: str
#     message_count: int
#     account_photo_url: str | None
#     user_photo_url: str | None
#     user_information: dict | None
#     user_insta_link: str | None
#     account_information: str | None
#     context: str | None
#     messages: list[MessageSchema]