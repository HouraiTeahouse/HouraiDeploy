import os, json
import logging
from util import namedtuple_from_mapping
from flask import Flask, request
from notify import DiscordNotifier
from deploy import DeployEvent, UnityGameDeploy, GitDeploy, UploadDeploy, get_platform

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1024 ** 3

with open('/var/htwebsite/deploy_config.json', 'r') as config_file:
    config = namedtuple_from_mapping(json.load(config_file))

discord = DiscordNotifier(config)
NOTIFIERS = [DiscordNotifier(config)]

DEPLOY_HANDLERS = {
    'git': [GitDeploy(config, notifiers=NOTIFIERS)],
    'upload': [UploadDeploy(config, notifiers=NOTIFIERS)],
    'unity': [UnityGameDeploy(config, notifiers=NOTIFIERS)]
}

@app.route('/<deploy_type>/<target>', methods=['POST'])
@app.route('/<deploy_type>/<target>/<branch>', methods=['POST'])
@app.route('/<deploy_type>/<target>/<branch>/<platform>', methods=['POST'])
def deploy(deploy_type, target, branch=None, platform='Windows'):
    platform = get_platform(platform)
    request_token = request.args.get('token')
    if request_token != config.DEPLOY_TOKEN:
        return 'Invalid request', 400
    print('VALID TOKEN')
    if deploy_type not in DEPLOY_HANDLERS:
        return "Invalid deployment type: %s" % deploy_type, 400
    print('VALID DEPLOY TYPE')
    print('DEPLOYING')
    event = DeployEvent(target, branch, platform, config)
    for handler in DEPLOY_HANDLERS[deploy_type]:
        try:
            handler.deploy(event)
        except Exception as error:
            # logging.error(error)
            discord.notify("Webhook failed: %s" % error)
            return "Deployment failed.", 500
    return "Deployment of {} on {} finished.".format(target, branch), 200
