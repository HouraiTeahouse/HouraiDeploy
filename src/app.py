import os, json
import logging
from util import namedtuple_from_mapping
from flask import Flask, request
from notify import DiscordNotifier
from deploy import DeployEvent, UnityGameDeploy, GitDeploy

app = Flask(__name__)

with open('/var/htwebsite/deploy_config.json', 'r') as config_file:
    config = namedtuple_from_mapping(json.load(config_file))

discord = DiscordNotifier(config)
NOTIFIERS = [DiscordNotifier(config)]

DEPLOY_HANDLERS = {
    'git': [GitDeploy(config, notifiers=NOTIFIERS)],
    'unity': [UnityGameDeploy(config, notifiers=NOTIFIERS)]
}

@app.route('/<deploy_type>/<target>', methods=['POST'])
@app.route('/<deploy_type>/<target>/<branch>', methods=['POST'])
def deploy(deploy_type, target, branch=None):
    print('INPUT')
    request_token = request.args.get('token')
    if request_token != config.DEPLOY_TOKEN:
        return 'Invalid request', 400
    print('VALID TOKEN')
    if deploy_type not in DEPLOY_HANDLERS:
        return "Invalid deployment type: %s" % deploy_type, 400
    print('VALID DEPLOY TYPE')
    print('DEPLOYING')
    event = DeployEvent(target, branch)
    for handler in DEPLOY_HANDLERS[deploy_type]:
        try:
            print(handler)
            handler.deploy(event)
        except Exception as error:
            # logging.error(error)
            discord.notify("Webhook failed: %s" % error)
            return "Deployment failed.", 500
    return "Deployment of {} on {} finished.".format(target, branch), 200
