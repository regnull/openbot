from openbot.db.models import Actor, BotProfile, ExternalProfile


def bot_actor(handle: str, name: str | None = None, description: str = "", provider: str = "openai",
              model: str = "m", **profile) -> Actor:
    return Actor(kind="bot", handle=handle, name=name or handle.title(), description=description,
                 bot=BotProfile(provider=provider, model=model, **profile))


def human_actor(handle: str = "you", name: str = "You") -> Actor:
    return Actor(kind="human", handle=handle, name=name)


def cron_actor(handle: str = "cron", name: str = "Cron") -> Actor:
    return Actor(kind="system", handle=handle, name=name)


def external_actor(handle: str, name: str | None = None, webhook_url: str | None = None,
                   webhook_secret: str | None = None) -> Actor:
    return Actor(kind="external", handle=handle, name=name or handle,
                 external=ExternalProfile(webhook_url=webhook_url, webhook_secret=webhook_secret))
