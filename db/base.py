import asyncio

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
                        Index)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.ext.asyncio import (create_async_engine,
                                    AsyncSession,
                                    async_sessionmaker)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy import select, func
from sqlalchemy.orm import column_property

from utils.enums import MessageStatusEnum, MessageTypeEnum, SessionStatusEnum

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
                      nullable=False,
                      unique=True)
    
    threads = relationship(
        "Thread",
        back_populates="insta_user"
    )
    # password = Column(String)
    # session = Column(JSONB,
    #                  nullable=True,
    #                  default=None)
    # updated_at = Column(TIMESTAMP(timezone=True))
    #
    # email = Column(String,
    #                unique=True,
    #                nullable=False)
    # hash_password = Column(String,
    #                        unique=True,
    #                        nullable=False)
    # #
    # name = Column(String,
    #               nullable=True)
    # age = Column(Integer,
    #              nullable=True)
    # city = Column(String,
    #               nullable=True)
    # country = Column(String,
    #                  nullable=True)
    # about = Column(String,
    #                nullable=True,
    #                default=None)
    # is_premium = Column(Boolean,
    #                     default=False)
    # is_vip = Column(Boolean,
    #                 default=False)
    # created_at = Column(TIMESTAMP(timezone=True))
    # updated_at = Column(TIMESTAMP(timezone=True))
    # message_notifications = Column(Boolean,
    #                                default=True)
    # ai_model_id = Column(Integer,
    #                      ForeignKey('ai_models.id'),
    #                      nullable=True,
    #                      default=None)
    # refresh_token = Column(String,
    #                        nullable=True)
    # ai_model = relationship('AIModel',
    #                         back_populates="users")
    # photos = relationship('Photo',
    #                       back_populates="user")
    # messages = relationship("Message",
    #                         back_populates="sender")
    # chat_links = relationship(
    #     "ChatParticipant",
    #     back_populates="user",
    #     cascade="all, delete-orphan"
    # )


class Account(Base):
    __tablename__ = 'accounts'
    
    id = Column(BigInteger,
                primary_key=True,
                index=True)
    insta_id = Column(String,
                      nullable=True,
                      default=None)
    username = Column(String,
                      nullable=False,
                      unique=True)
    password = Column(String)
    session = Column(JSONB,
                     nullable=True,
                     default=None)
    is_active = Column(String,
                       default=SessionStatusEnum.INACTIVE)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=True,
                        default=None)
    updated_at = Column(TIMESTAMP(timezone=True), # время последнего polling`а
                        nullable=True,
                        default=None)
    proxy_url = Column(String,
                      nullable=True,
                      default=None)
    is_parse = Column(Boolean,
                      default=True)
    ai_model_id = Column(Integer,
                         ForeignKey('ai_models.id'),
                         nullable=True,
                         default=None)
    
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

# class Photo(Base):
#     __tablename__ = "photos"

#     id = Column(Integer,
#                 primary_key=True,
#                 index=True)

#     url = Column(String(2048),
#                  nullable=False,
#                  unique=True)

#     is_main = Column(Boolean,
#                      nullable=False,
#                      default=False)

#     user_id = Column(
#         BigInteger,
#         ForeignKey("users.id",
#         ondelete="CASCADE"),
#         nullable=False
#     )

#     user = relationship("User", back_populates="photos")

#     __table_args__ = (
#         Index(
#             "ux_user_main_photo",
#             "user_id",
#             unique=True,
#             postgresql_where=is_main.is_(True)
#         ),
#     )


class AIModel(Base):
    __tablename__ = 'ai_models'

    id = Column(Integer,
                primary_key=True,
                index=True)
    name = Column(String)

    accounts = relationship('Account',
                          back_populates="ai_model")
    





# class ChatParticipant(Base):
#     __tablename__ = "chat_participants"

#     chat_id = Column(
#         Integer,
#         ForeignKey("chats.id", ondelete="CASCADE"),
#         primary_key=True
#     )

#     user_id = Column(
#         BigInteger,
#         ForeignKey("users.id", ondelete="CASCADE"),
#         primary_key=True
#     )

#     joined_at = Column(TIMESTAMP(timezone=True))

#     chat = relationship(
#         "Chat",
#         back_populates="_participants"
#     )

#     user = relationship(
#         "User",
#         back_populates="chat_links"
#     )


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
    # is_read = Column(Boolean,
    #                  default=False)
#     sender_id = Column(
#         BigInteger,
#         ForeignKey("users.id",
#         ondelete="CASCADE"),
#         nullable=False
#     )
    thread_id = Column(
        BigInteger,
        ForeignKey(
            "threads.id",
            ondelete="CASCADE",
            # name="fk_messages_chat_id"
        ),
        nullable=False
    )
    thread = relationship(
        "Thread",
        back_populates="messages",
        foreign_keys=[thread_id]
    )

    attachment = relationship(
        "Attachment",
        back_populates="message",
        uselist=False  # 💥 обязательно для 1-1
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
        unique=True
    )

    message = relationship(
        "Message",
        back_populates="attachment",
        uselist=False
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
    last_message_id = Column(Text)
    context = Column(Text)
    account_id = Column(
        BigInteger,
        ForeignKey("accounts.id",
        ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    is_approved = Column(Boolean, default=False)
    insta_user_id = Column(
        BigInteger,
        ForeignKey("users.id",
        ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    
    account = relationship("Account", back_populates="threads")
    insta_user = relationship("InstaUser", back_populates="threads")
    # last_message = relationship(
    #     "Message",
    #     foreign_keys=[last_message_id],
    #     uselist=False
    # )

    # _participants = relationship(
    #     "ChatParticipant",
    #     back_populates="chat",
    #     cascade="all, delete-orphan"
    # )

    # users = relationship(
    #     "User",
    #     secondary="chat_participants",
    #     viewonly=True
    # )
    messages = relationship(
        "Message",
        back_populates="thread",
        cascade="all, delete-orphan"
    )

    messages_count = column_property(
        select(func.count(Message.id))
        .where(
            Message.thread_id == id,
            Message.status == MessageStatusEnum.PENDING,
        )
        .correlate_except(Message)
        .scalar_subquery()
    )



engine = create_async_engine(
    db_url,
    pool_size=10,          # число постоянных соединений в пуле
    max_overflow=20,       # доп. соединения при пиках нагрузки
    pool_timeout=30,       # таймаут ожидания соединения
    echo=True,            # можно поставить True для логов SQL
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