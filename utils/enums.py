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


class ThreadColorEnum(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    GREY = "grey"


class AIModelEnum(str, Enum):
    CLAUDE_SONNET_5 = 'anthropic/claude-sonnet-5'
    CLAUDE_OPUS_4_8 = 'anthropic/claude-opus-4.8'
    CLAUDE_OPUS_4_6 = 'anthropic/claude-opus-4.6'
    DEEPSEEK_LATEST = "deepseek/deepseek-v4-flash-latest"
    QWEN_3 = 'qwen/qwen3-14b'
    QWEN_ORCA = 'obsidian/Qwen3.8-27B'
    GLM_FREE = 'z-ai/glm-5.2:free'