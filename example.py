import asyncio

import tortoise_trace_unused
tortoise_trace_unused.hook_tortoise()

from tortoise import Model, fields, Tortoise
from tortoise.contrib.test import MEMORY_SQLITE


class User(Model):
    id: int = fields.BigIntField(primary_key=True)
    name: str = fields.TextField()

    _KNOWN_UNUSED = ("_username",)


class Username(Model):
    id: int = fields.BigIntField(primary_key=True)
    username: str = fields.CharField(max_length=64)
    user: User = fields.OneToOneField("models.User", related_name="username")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.id!r})"


async def main() -> None:
    await Tortoise.init(db_url=MEMORY_SQLITE, modules={"models": ["__main__"]})
    await Tortoise.generate_schemas()

    user = await User.create(name="test user")
    await Username.create(user=user, username="test_user")

    user = await User.get(id=user.id).select_related("username")
    print(user)

    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.new_event_loop().run_until_complete(main())
