from enum import Enum


class MessageTypeEnum(str, Enum):
    TEXT = "text"
    VIDEO = "video"
    PHOTO = "photo"
    AUDIO = "audio"
    AUDIOMESSAGE = "audiomessage"
    VIDEOMESSAGE = "videomessage"


class MessageStatusEnum(str, Enum):
    APPROVED = "approved"
    MODERATED = "moderated"
    PENDING = "pending"
    REJECTED = 'rejected'



class SessionStatusEnum(str, Enum):
    ACTIVE = 'active'
    PROCESS = 'process'
    INACTIVE = 'inactive'