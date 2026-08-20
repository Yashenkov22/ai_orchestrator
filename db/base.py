import enum

from sqlalchemy import (Column,
                        Integer,
                        String,
                        DATETIME,
                        ForeignKey,
                        Text,
                        Float,
                        DateTime,
                        TIMESTAMP,
                        BLOB,
                        JSON,
                        BigInteger,
                        Table,
                        Boolean,
                        Index,
                        Enum)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.ext.asyncio import (create_async_engine,
                                    AsyncSession,
                                    async_sessionmaker)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy import select, func
from sqlalchemy.orm import column_property

from utils.enums import AIModelEnum, MessageStatusEnum, MessageTypeEnum, SessionStatusEnum, ThreadColorEnum

from config import db_url


Base = declarative_base()
# Base = automap_base()


class InstaUser(Base):
    __tablename__ = 'users'
    
    id = Column(BigInteger,
                primary_key=True,
                index=True)
    insta_id = Column(String,
                      nullable=True,
                      default=None)
    username = Column(String,
                      nullable=True,
                      default=None)
    full_name = Column(String,
                      nullable=True,
                      default=None)
    photo_url =Column(String(2048),
                      nullable=True,
                      default=None,
                      unique=True)
    
    threads = relationship(
        "Thread",
        back_populates="insta_user"
    )


class Account(Base):
    __tablename__ = 'accounts'
    
    id = Column(BigInteger,
                primary_key=True,
                index=True)
    insta_id = Column(String,
                      nullable=True,
                      default=None)
    full_name = Column(String,
                      nullable=True,
                      default=None)
    photo_url =Column(String(2048),
                      nullable=True,
                      default=None,
                      unique=True)
    username = Column(String,
                      nullable=False,
                      unique=True)
    view_name = Column(String,
                      nullable=True,
                      default=None)
    password = Column(String)
    # session = Column(JSONB,
    #                  nullable=True,
    #                  default=None)
    # is_active = Column(String,
    #                    default=SessionStatusEnum.INACTIVE)
    has_error = Column(Boolean,
                      default=False,
                      server_default="false")
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=True,
                        default=None)
    updated_at = Column(TIMESTAMP(timezone=True), # время последнего polling`а
                        nullable=True,
                        default=None)
    proxy_url = Column(String,
                      nullable=True,
                      default=None)
    is_active = Column(Boolean,
                      default=True,
                      server_default="false")
    is_hidden = Column(Boolean, default=False,
                        server_default='false')
    parse_whole_thread_list = Column(Boolean,
                                     default=False,
                                     nullable=False,
                                     server_default='false')
    # ai settings
    ai_model_id = Column(Integer,
                         ForeignKey('ai_models.id'),
                         nullable=True,
                         default=None)
    folder_id = Column(String,
                      nullable=True,
                      default=None)
    profile_id = Column(String,
                        nullable=True,
                        default=None)
    information = Column(Text)
    #
    
    ai_model = relationship('AIModel',
                            back_populates="accounts")
    
    threads = relationship(
        "Thread",
        back_populates="account",
        cascade="all, delete-orphan"
    )


class Admin(Base):
    __tablename__ = 'admins'
    
    id = Column(BigInteger,
                primary_key=True,
                index=True)
    username = Column(String,
                      nullable=False,
                      unique=True)
    password = Column(String)
    refresh_token = Column(String,
                           nullable=True)



class AIModel(Base):
    __tablename__ = 'ai_models'

    id = Column(Integer,
                primary_key=True,
                index=True)
    name = Column(String)

    accounts = relationship('Account',
                          back_populates="ai_model")


class Message(Base):
    __tablename__ = 'messages'
    
    id = Column(BigInteger,
                primary_key=True,
                index=True)
    #
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=True,
                        default=None)
    updated_at = Column(TIMESTAMP(timezone=True),
                        nullable=True,
                        default=None)
    text = Column(Text,
                  nullable=True,
                  default=None)
    # type = Column(String,
    #               nullable=False,
    #               default=MessageTypeEnum.TEXT)
    sender = Column(String,
                    nullable=False)
    status = Column(String,
                    nullable=False,
                    default=MessageStatusEnum.PENDING)
    translated_text = Column(Text,
                  nullable=True,
                  default=None,
                  server_default=None)
    retry_send_count = Column(Integer,
                              default=0,
                              server_default='0')

    thread_id = Column(
        BigInteger,
        ForeignKey(
            "threads.id",
            ondelete="CASCADE",
        ),
        nullable=False
    )
    thread = relationship(
        "Thread",
        back_populates="messages",
        foreign_keys=[thread_id]
    )

    attachments = relationship(
        "Attachment",
        back_populates="message",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Attachment(Base):
    __tablename__ = 'attachments'

    # предполагаю только фото и видео (пока)
    
    id = Column(BigInteger,
                primary_key=True,
                index=True)
    media_type = Column(String)
    media_url = Column(String)

    message_id = Column(
        BigInteger,
        ForeignKey("messages.id",
                   ondelete="CASCADE"),
        nullable=False,
    )

    message = relationship(
        "Message",
        back_populates="attachments"
    )



class Thread(Base):
    __tablename__ = 'threads'

    id = Column(Integer,
                primary_key=True,
                index=True)
    thread_id = Column(Text)
    timestamp_last_seen_message = Column(TIMESTAMP(timezone=True),
                                         nullable=True,
                                         default=None)
    # last_message_id = Column(Text)
    last_message_id = Column(Integer,
                             default=0,
                             server_default='0')
    context = Column(Text)
    account_id = Column(
        BigInteger,
        ForeignKey("accounts.id",
        ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    is_approved = Column(Boolean, default=False)
    is_blocked = Column(Boolean, default=False,
                        server_default='false')
    proccess_block = Column(Boolean, default=False,
                        server_default='false')
    # is_spam = Column(Boolean, default=False)
    insta_user_id = Column(
        BigInteger,
        ForeignKey("users.id",
        ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    notes = Column(Text)
    is_unread = Column(Boolean,
                       default=True)
    is_pinned = Column(Boolean,
                       default=False,
                       server_default='false')
    user_information = Column(JSONB,
                              nullable=True,
                              default=None)
    original_user_information = Column(JSONB,
                                       nullable=True,
                                       default=None)
    color_level = Column(String,
                         nullable=False,
                         default=ThreadColorEnum.GREY)
    # ai_model = Column(String,
    #                   nullable=False,
    #                   default=AIModelEnum.CLAUDE_SONNET_5,
    #                   server_default='anthropic/claude-sonnet-5')
    # ai_temperature = Column(Float,
    #                         default=0.5,
    #                         server_default='0.5')
    
    account = relationship("Account", back_populates="threads")
    insta_user = relationship("InstaUser", back_populates="threads")

    messages = relationship(
        "Message",
        back_populates="thread",
        cascade="all, delete-orphan"
    )

    # messages_count = column_property(
    #     select(func.count(Message.id))
    #     .where(
    #         Message.thread_id == id,
    #         Message.status == MessageStatusEnum.PENDING,
    #     )
    #     .correlate_except(Message)
    #     .scalar_subquery()
    # )



engine = create_async_engine(
    db_url,
    pool_size=10,          # число постоянных соединений в пуле
    max_overflow=20,       # доп. соединения при пиках нагрузки
    pool_timeout=30,       # таймаут ожидания соединения
    echo=False,            # можно поставить True для логов SQL
)

# Асинхронная сессия
session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

# Рефлексия схемы (требует отдельного подключения)
# async def init_models():
#     async with engine.begin() as conn:
#         await conn.run_sync(lambda sync_conn: Base.prepare(autoload_with=sync_conn))
#     print("✅ Database schema reflected successfully.")


async def init_models():
    async with engine.begin() as conn:
        # Создаем таблицы
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database schema created successfully.")


# Пример получения сессии
async def get_session():
    async with session() as _session:
        yield _session