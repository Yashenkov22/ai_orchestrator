from fastapi import HTTPException, status


DB_ERROR_EXCEPTION = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                   detail='Error with DB connection')


NOT_AUTHENTICATED_EXCEPTION = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


class ChatNotFound(Exception):
    pass


class NotAccessToChat(Exception):
    pass