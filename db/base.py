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
                        Enum,
                        UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.ext.asyncio import (create_async_engine,
                                    AsyncSession,
                                    async_sessionmaker)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy import select, func
from sqlalchemy.orm import column_property

from utils.enums import (AIModelEnum,
                         LanguageEnum,
                         MessageStatusEnum,
                         MessageTypeEnum,
                         SessionStatusEnum,
                         ThreadColorEnum,
                         ScenarioStatus,
                         ScenarioEvaluationType)

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

    coffee_photos = relationship(
        "CoffeeScenarioPhoto",
        back_populates="account",
        cascade="all, delete-orphan"
    )


class CoffeeScenarioPhoto(Base):
    __tablename__ = "coffee_scenario_photos"

    id = Column(
        BigInteger,
        primary_key=True,
        index=True,
    )

    account_id = Column(
        BigInteger,
        ForeignKey("accounts.id",
        ondelete="SET NULL"),
        nullable=True,
        default=None,
    )

    media_url = Column(
        String(2048),
        nullable=False
    )

    purpose = Column(
        String(50),
        nullable=False
    )

    account = relationship(
        "Account",
        back_populates="coffee_photos"
    )


# class CoffeeScenarioSupply(Base):
#     __tablename__ = "coffee_scenario_supplies"

#     id = Column(
#         BigInteger,
#         primary_key=True,
#         index=True
#     )

#     account_id = Column(
#         BigInteger,
#         ForeignKey("accounts.id", ondelete="CASCADE"),
#         nullable=False,
#         unique=True,
#         index=True
#     )

#     account = relationship(
#         "Account",
#         back_populates="coffee_scenario_supply"
#     )

#     photos = relationship(
#         "CoffeeScenarioPhoto",
#         back_populates="supply",
#         cascade="all, delete-orphan"
#     )
# class AccountMedia(Base):
#     __tablename__ = "account_media"

#     id = Column(
#         BigInteger,
#         primary_key=True,
#         index=True,
#     )

#     account_id = Column(
#         BigInteger,
#         ForeignKey("accounts.id", ondelete="CASCADE"),
#         nullable=False,
#         index=True,
#     )

#     # photo / video
#     media_type = Column(
#         String(50),
#         nullable=False,
#     )

#     # Например:
#     # avatar
#     # greeting
#     # scenario
#     # coffee
#     # thank_you
#     # generic
#     marker = Column(
#         String(100),
#         nullable=True,
#         default=None,
#         index=True,
#     ) # возможно Enum

#     # Человеческое название:
#     # "Фото с кофе"
#     # "Видео из кафе"
#     name = Column(
#         String(255),
#         nullable=True,
#         default=None,
#     )

#     # Путь или URL к файлу
#     media_url = Column(
#         String(2048),
#         nullable=False,
#     )

#     account = relationship(
#         "Account",
#         back_populates="media",
#     )


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
    type = Column(String,
                  nullable=False,
                  default=MessageTypeEnum.TEXT,
                  server_default='text')
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

################ new idea

# class Scenario(Base):
#     __tablename__ = "scenarios"

#     id = Column(
#         BigInteger,
#         primary_key=True,
#         index=True,
#     )

#     name = Column(
#         String(255),
#         nullable=False,
#     )

#     description = Column(
#         Text,
#         nullable=True,
#     )

#     created_at = Column(
#         TIMESTAMP(timezone=True),
#         nullable=True,
#         default=None,
#     )

#     updated_at = Column(
#         TIMESTAMP(timezone=True),
#         nullable=True,
#         default=None,
#     )

#     steps = relationship(
#         "ScenarioStep",
#         back_populates="scenario",
#         cascade="all, delete-orphan",
#         order_by="ScenarioStep.order",
#     )

#     # наводящие вопросы с вероятностным выбором ответа из перечня для дальнейших переходов к другим шагам
#     evaluations = relationship(
#         "ScenarioEvaluation",
#         back_populates="scenario",
#         cascade="all, delete-orphan",
#     )

#     thread_scenarios = relationship(
#         "ThreadScenario",
#         back_populates="scenario",
#         cascade="all, delete-orphan",
#     )

# class ScenarioStep(Base):
#     __tablename__ = "scenario_steps"

#     id = Column(
#         BigInteger,
#         primary_key=True,
#         index=True,
#     )

#     scenario_id = Column(
#         BigInteger,
#         ForeignKey(
#             "scenarios.id",
#             ondelete="CASCADE",
#         ),
#         nullable=False,
#         index=True,
#     )

#     order = Column(
#         Integer,
#         nullable=False,
#     )

#     name = Column(
#         String(255),
#         nullable=False,
#     )

#     # action
#     instructions = Column(
#         Text,
#         nullable=False,
#     )

#     scenario = relationship(
#         "Scenario",
#         back_populates="steps",
#     )

#     # наводящие вопросы с вероятностным выбором ответа из перечня для дальнейших переходов к другим шагам
#     # evaluations = relationship(

#     #     "ScenarioEvaluation",

#     #     back_populates="step",

#     #     cascade="all, delete-orphan",

#     #     order_by="ScenarioEvaluation.id",

#     # )

#     outgoing_transitions = relationship(
#         "ScenarioTransition",
#         foreign_keys="ScenarioTransition.from_step_id",
#         back_populates="from_step",
#         cascade="all, delete-orphan",
#     )

#     incoming_transitions = relationship(
#         "ScenarioTransition",
#         foreign_keys="ScenarioTransition.to_step_id",
#         back_populates="to_step",
#     )

#     __table_args__ = (
#         UniqueConstraint(
#             "scenario_id",
#             "order",
#             name="uq_scenario_step_order",
#         ),
#     )


# class ScenarioTransitionCondition(Base):
#     __tablename__ = "scenario_transition_conditions"

#     id = Column(
#         BigInteger,
#         primary_key=True,
#         index=True,
#     )

#     transition_id = Column(
#         BigInteger,
#         ForeignKey(
#             "scenario_transitions.id",
#             ondelete="CASCADE",
#         ),
#         nullable=False,
#         index=True,
#     )

#     evaluation_id = Column(
#         BigInteger,
#         ForeignKey(
#             "scenario_evaluations.id",
#             ondelete="CASCADE",
#         ),
#         nullable=False,
#         index=True,
#     )

#     operator = Column(
#         String(50),
#         nullable=False,
#     )

#     value = Column(
#         String(255),
#         nullable=False,
#     )

#     min_probability = Column(
#         Float,
#         nullable=True,
#     )

#     transition = relationship(
#         "ScenarioTransition",
#         back_populates="conditions",
#     )

#     evaluation = relationship(
#         "ScenarioEvaluation",
#     )


# # типизированный вероятностный вопрос ответ
# class ScenarioEvaluation(Base):
#     __tablename__ = "scenario_evaluations"

#     id = Column(
#         BigInteger,
#         primary_key=True,
#         index=True,
#     )

#     scenario_id = Column(
#         BigInteger,
#         ForeignKey(
#             "scenarios.id",
#             ondelete="CASCADE",
#         ),
#         nullable=False,
#         index=True,
#     )

#     question = Column(
#         Text,
#         nullable=False,
#     )

#     type = Column(
#         String(50),
#         nullable=False,
#     )

#     choices = Column(
#         JSONB,
#         nullable=True,
#     )

#     scenario = relationship(
#         "Scenario",
#         back_populates="evaluations",
#     )


# class ScenarioTransition(Base):
#     __tablename__ = "scenario_transitions"

#     id = Column(
#         BigInteger,
#         primary_key=True,
#         index=True,
#     )

#     from_step_id = Column(
#         BigInteger,
#         ForeignKey(
#             "scenario_steps.id",
#             ondelete="CASCADE",
#         ),
#         nullable=False,
#         index=True,
#     )

#     to_step_id = Column(
#         BigInteger,
#         ForeignKey(
#             "scenario_steps.id",
#             ondelete="SET NULL",
#         ),
#         nullable=True,
#         index=True,
#     )

#     # name = Column(
#     #     String(255),
#     #     nullable=False,
#     # )

#     # conditions = Column(
#     #     JSONB,
#     #     nullable=True,
#     #     default=None,
#     # )

#     # priority = Column(
#     #     Integer,
#     #     nullable=False,
#     #     default=0,
#     #     server_default="0",
#     # )

#     from_step = relationship(
#         "ScenarioStep",
#         foreign_keys=[from_step_id],
#         back_populates="outgoing_transitions",
#     )

#     to_step = relationship(
#         "ScenarioStep",
#         foreign_keys=[to_step_id],
#         back_populates="incoming_transitions",
#     )

#     conditions = relationship(
#         "ScenarioTransitionCondition",
#         back_populates="transition",
#         cascade="all, delete-orphan",
#     )


# class ThreadScenario(Base):
#     __tablename__ = "thread_scenarios"

#     id = Column(
#         BigInteger,
#         primary_key=True,
#         index=True,
#     )

#     thread_id = Column(
#         BigInteger,
#         ForeignKey(
#             "threads.id",
#             ondelete="CASCADE",
#         ),
#         nullable=False,
#         index=True,
#     )
#     scenario_id = Column(
#         BigInteger,
#         ForeignKey(
#             "scenarios.id",
#             ondelete="CASCADE",
#         ),
#         nullable=False,
#         index=True,
#     )

#     current_step_id = Column(
#         BigInteger,
#         ForeignKey(
#             "scenario_steps.id",
#             ondelete="SET NULL",
#         ),
#         nullable=True,
#         index=True,
#     )

#     status = Column(
#         String(50),
#         nullable=False,
#         default=ScenarioStatus.ACTIVE.value,
#         server_default=ScenarioStatus.ACTIVE.value,
#         # index=True,
#     )

#     state = Column(
#         JSON,
#         nullable=False,
#         default=dict,
#     )

#     started_at = Column(
#         TIMESTAMP(timezone=True),
#         nullable=True,
#         default=None,
#     )

#     completed_at = Column(
#         TIMESTAMP(timezone=True),
#         nullable=True,
#         default=None,
#     )

#     updated_at = Column(
#         TIMESTAMP(timezone=True),
#         nullable=True,
#         default=None,
#     )

#     thread = relationship(
#         "Thread",
#         back_populates="thread_scenarios",
#     )

#     scenario = relationship(
#         "Scenario",
#         back_populates="thread_scenarios",
#     )

#     current_step = relationship(
#         "ScenarioStep",
#         foreign_keys=[current_step_id],
#     )

#     __table_args__ = (
#         UniqueConstraint(
#             "thread_id",
#             "scenario_id",
#             name="uq_thread_scenario",
#         ),
#     )

############ end new idea

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
    ai_model = Column(String,
                      nullable=False,
                      default=AIModelEnum.CLAUDE_SONNET_5,
                      server_default='anthropic/claude-sonnet-5')
    ai_temperature = Column(Float,
                            default=0.5,
                            server_default='0.5')
    language = Column(String,
                      nullable=False,
                      default=LanguageEnum.ENGLISH,
                      server_default='English')

    coffee_state = Column(JSONB,
                          nullable=True,
                          default=None)

    # coffee_state = {
    #     'status': '', # возможно Enum, статус задачи/сценария
    #     'logs': {
    #         'step_1': '',
    #         'step_2': '',
    #         'step_3': '',
    #         'step_4': '',
    #     },
    #     'current_step': '',
    # }
    
    account = relationship("Account", back_populates="threads")
    insta_user = relationship("InstaUser", back_populates="threads")

    messages = relationship(
        "Message",
        back_populates="thread",
        cascade="all, delete-orphan"
    )

    # thread_scenarios = relationship(
    #     "ThreadScenario",
    #     back_populates="thread",
    #     cascade="all, delete-orphan",
    #     lazy="selectin",
    # )


# class ScenarioThread(Base):
#     __tablename__ = 'scenario_threads'

#     # steps structure (снимок шагов сценария + состояние прохождения в этом чате):
#     # {
#     #     "1": {
#     #         'action': 'str',   — копируется из Scenario.steps на момент привязки
#     #         'status': 'не выполнено',  ['не выполнено', 'в процессе', 'выполнено']
#     #         'result': ''       — str | {'key': 'value'}
#     #     },
#     #     "2": {...},
#     # }

#     id = Column(BigInteger,
#                 primary_key=True,
#                 index=True)

#     thread_id = Column(
#         Integer,                         # Thread.id у вас Integer
#         ForeignKey("threads.id", ondelete="CASCADE"),
#         nullable=False,
#     )
#     scenario_id = Column(
#         Integer,                         # Scenario.id у вас Integer
#         ForeignKey("scenarios.id", ondelete="CASCADE"),
#         nullable=False,
#     )

#     states = Column(JSONB,                # снимок + состояние; не ссылаемся на шаблон
#                    nullable=False,
#                    server_default='{}')

#     is_active = Column(Boolean,          # включён/выключен в этом чате
#                        default=True,
#                        server_default='true')
#     is_completed = Column(Boolean,       # все обязательные шаги выполнены / достигнут "конец сценария"
#                           default=False,
#                           server_default='false')

#     real_time = Column(Boolean,          # снимок Scenario.real_time на момент привязки (опц.)
#                        default=False,
#                        server_default='false')

#     completed_at = Column(TIMESTAMP(timezone=True),
#                           nullable=True,
#                           default=None)
#     created_at = Column(TIMESTAMP(timezone=True),
#                         nullable=True,
#                         default=None)
#     updated_at = Column(TIMESTAMP(timezone=True),
#                         nullable=True,
#                         default=None)

#     thread = relationship("Thread",
#                           back_populates="scenario_threads")
#     scenario = relationship("Scenario",
#                             back_populates="scenario_threads",
#                             lazy="selectin")

#     __table_args__ = (
#         UniqueConstraint("thread_id", "scenario_id",
#                          name="uq_scenario_thread"),
#     )


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