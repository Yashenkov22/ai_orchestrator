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
    DEEPSEEK_LATEST = "deepseek/deepseek-v4-flash-0731"
    QWEN_3 = 'qwen/qwen3-14b'
    QWEN_ORCA = 'obsidian/Qwen3.8-27B'
    GLM_FREE = 'z-ai/glm-5.2:free'
    GLM_4_6 = 'z-ai/glm-4.6'


class LanguageEnum(str, Enum):
    AFRIKAANS = "Afrikaans"
    ARABIC = "Arabic"
    BENGALI = "Bengali"
    BULGARIAN = "Bulgarian"
    CANTONESE = "Cantonese"
    CHINESE = "Chinese"
    CROATIAN = "Croatian"
    CZECH = "Czech"
    DANISH = "Danish"
    DUTCH = "Dutch"
    ENGLISH = "English"
    FINNISH = "Finnish"
    FILIPINO = "Filipino"
    FRENCH = "French"
    GERMAN = "German"
    GREEK = "Greek"
    GUJARATI = "Gujarati"
    HEBREW = "Hebrew"
    HINDI = "Hindi"
    HUNGARIAN = "Hungarian"
    INDONESIAN = "Indonesian"
    ITALIAN = "Italian"
    JAPANESE = "Japanese"
    KANNADA = "Kannada"
    KOREAN = "Korean"
    MALAY = "Malay"
    MALAYALAM = "Malayalam"
    MARATHI = "Marathi"
    NIGERIAN_PIDGIN = "Nigerian Pidgin"
    NORWEGIAN = "Norwegian"
    ODIA = "Odia"
    PERSIAN = "Persian"
    POLISH = "Polish"
    PORTUGUESE = "Portuguese"
    PUNJABI = "Punjabi"
    ROMANIAN = "Romanian"
    RUSSIAN = "Russian"
    SERBIAN = "Serbian"
    SLOVAK = "Slovak"
    SPANISH = "Spanish"
    SWAHILI = "Swahili"
    SWEDISH = "Swedish"
    TAMIL = "Tamil"
    TELUGU = "Telugu"
    THAI = "Thai"
    TURKISH = "Turkish"
    UKRAINIAN = "Ukrainian"
    URDU = "Urdu"
    VIETNAMESE = "Vietnamese"
    ZULU = "Zulu"