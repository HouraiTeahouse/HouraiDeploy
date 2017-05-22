import requests
import abc

class NotificationHandler(object):

    def __init__(self, config):
        self.config = config

    @abc.abstractmethod
    def notify(self, message):
        raise NotImplementedError


class DiscordNotifier(NotificationHandler):

    def notify(self, message):
        if message is str:
            requests.post(self.config.DISCORD_WEBHOOK, json={ "content": message })
        else:
            requests.post(self.config.DISCORD_WEBHOOK, json=message)
