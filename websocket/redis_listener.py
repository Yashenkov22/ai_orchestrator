import json
import asyncio

from redis.asyncio import Redis

from .base import manager

from config import REDIS_HOST, REDIS_PASSWORD, REDIS_PORT

redis = Redis(
    host=REDIS_HOST,
    password=REDIS_PASSWORD,
    port=REDIS_PORT,
    decode_responses=True,
)


# async def redis_listener():
#     pubsub = redis.pubsub()

#     await pubsub.subscribe("notifications")

#     async for message in pubsub.listen():

#         if message["type"] != "message":
#             continue

#         data = json.loads(message["data"])

#         await manager.send_to_user(
#             user_id=data["user_id"],
#             message=data,
#         )

async def redis_listener():
    pubsub = redis.pubsub()

    await pubsub.subscribe("notifications")

    try:
        async for message in pubsub.listen():

            if message["type"] != "message":
                continue

            data = json.loads(message["data"])

            await manager.send_to_user(
                user_id=data["user_id"],
                message=data,
            )

    except asyncio.CancelledError:
        pass

    finally:
        await pubsub.unsubscribe("websocket_notifications")
        await pubsub.close()



async def publish_event(redis,
                        *,
                        type: str,
                        payload: dict):

    await redis.publish("notifications",
                        json.dumps({
                            "user_id": 1,
                            "type": type,
                            "payload": payload}))
    print(' + PUBLISH EVENT TO REDIS SUCCESSFULLY')