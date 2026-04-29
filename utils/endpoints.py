
from utils.schemas import NotificationsSchema, BaseParticipantSchema


def add_notifications_to_user(user):
    pass
    # user.notifications = NotificationsSchema(newMessages=user.message_notifications)

    # return user


# def add_participant_to_chats(chats: list[Chat],
#                              user_id: int):
#     for chat in chats:
        
#         _participant = [user for user in chat.users if user.id != user_id]
#         # _participant = [user for user in chat.users]

#         if _participant:
#             chat.participant = BaseParticipantSchema.model_construct(**_participant[0].__dict__)

#     return chats