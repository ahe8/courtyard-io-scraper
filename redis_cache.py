import redis


class RedisCache:
    def __init__(self, host='localhost', port=6379):
        self._redis_client = redis.Redis(host=host, port=port)
        self.expiration_time = 259200  # 3 days in seconds

    def get(self, key: str):
        return self._redis_client.json().get(key, "$")

    def set(self, key: str, val: dict) -> None:
        self._redis_client.json().set(key, "$", val)
        self._redis_client.expire(key, self.expiration_time)
