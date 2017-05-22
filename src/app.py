import os
import subprocess
import requests
import json
from util import namedtuple_from_mapping
from flask import Flask, request
from notify import DiscordNotifier
from deploy import DeployEvent, UnityGameDeploy, GitDeploy

app = Flask(__name__)

with open('/var/htwebsite/deploy_config.json', 'r') as config_file:
    config = namedtuple_from_mapping(json.load(config_file))

NOTIFIERS = [DiscordNotifier(config)]

DEPLOY_HANDLERS = {
    'git': [GitDeploy(config, notifiers=NOTIFIERS)],
    'unity': [UnityGameDeploy(config, notifiers=NOTIFIERS)]
}

@app.route('/<type>/<target>/<branch>', methods=['POST'])
def deploy(type, target, branch):
    request_token = request.args.get('token')
    if request_token != DEPLOY_TOKEN:
        return 'Invalid request', 400
    if type not in DEPLOY_HANDLERS:
        return "Invalid deployment type: %s" % type, 400
    try:
        event = DeployEvent(target, branch)
        for handler in DEPLOY_HANDLERS[type]:
            handler.deploy(event)
    except Exception:
        return "Deployment failed.", 500
    return "Deployment of {} on {} finished.".format(target, branch), 200
