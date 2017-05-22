import abc
import os
from flask import request

file_dir = os.path.dirname(os.path.realpath(__file__))
deploy_script = os.path.join(file_dir, 'deploy.sh')
bundle_script = os.path.join(file_dir, 'unity_bundles.sh')

class DeployEvent(object):

    def __init__(self, target, branch):
        self.target = target
        self.branch = branch


class DeployHandler(object):

    def __init__(self, config, notifiers=None):
        self.config = config
        if not notifiers:
            notifiers = []
        self.notifiers = list(notifiers)

    @abc.abstractmethod
    def deploy(self, event):
        raise NotImplementError

    def send_notifications(self, message):
        for notiifer in self.notifiers:
            notifier.notify(message)


class GitDeploy(DeployHandler):

    def deploy(self, event):
        git_dir = os.path.join(self.config.GIT_ROOT_PATH, target, '.git')
        if not os.path.isdir(git_dir):
            return "{} is not a valid target".format(target), 400
        branches = requests.get("https://api.github.com/repos/{0}/{1}/branches".format(
            self.config.GITHUB_ORG, event.target)).json()
        has_branch = any(event.branch == name for name in map(lambda x: x['name'], branches))
        if not has_branch:
            return 'Invalid branch', 400
        subprocess.Popen((deploy_script, target, branch))


class UnityGameDeploy(DeployHandler):

    BASE_UNITY_URL="https://build-api.cloud.unity3d.com"

    def __init__(self, config, notifiers=None):
        super().__init__(config, notifiers)
        self.unity_events = {
            "ProjectBuildQueued": self.Standard("queued"),
            "ProjectBuildStarted": self.Standard("started"),
            "ProjectBuildRestarted": self.Standard("restarted"),
            "ProjectBuildSuccess": self.Success,
            "ProjectBuildFailure": self.Failure,
            "ProjectBuildCanceled": self.Standard("canceled"),
        }

    def create_share_link(base_url, headers):
        print ('Creating share link...')
        headers = dict(headers)
        headers['Content-Type'] = 'application/json'
        share_request = requests.post(base_url + "/share", headers=headers)
        print ('Response: ' + str(share_request.json()))
        return "https://developer.cloud.unity3d.com/share/{0}/".format(share_request.json()['shareid'])

    def get_platform(self, platform):
        if "osx" in platform.lower():
            return "OSX"
        if "windows" in platform.lower():
            return "Windows"
        return "Linux";

    def Standard(self, message):
        def _create_content(json, target):
            self.send_notifications("`{}` build #{} for `{}` {}.".format(
                json["projectName"],
                json["buildNumber"],
                json["buildTargetName"],
                message))
        return _create_content

    def Success(self, json, target):
        content = "`{}` build #{} for `{}` finished.".format(
                json["projectName"],
                json["buildNumber"],
                json["buildTargetName"])
        base_url = BASE_UNITY_URL + json['links']['api_self']['href']
        headers = {'Authorization': 'Basic ' + UNITY_AUTH_TOKEN}
        share_link = "";
        if 'links' in json and 'share_url' in json['links']:
            share_link = json['links']['share_url']["href"]
        else:
            share_link = self.create_share_link(base_url, headers)
        content = content + "\n" + share_link
        req = requests.get(base_url, headers=headers)
        build_obj = req.json()
        branch = build_obj['scmBranch']
        platform = self.get_platform(build_obj['platform'])
        download_url = build_obj['links']['download_primary']['href']
        Popen((bundle_script, target, branch, platform, download_url))
        self.send_notifications(content)

    def Failure(self, json, target):
        content = "`{}` build #{} for `{}` failed.".format(
                json["projectName"],
                json["buildNumber"],
                json["buildTargetName"])
        base_url = BASE_UNITY_URL + json['links']['api_self']['href'] + '/log'
        headers = {'Authorization': 'Basic ' + self.config.UNITY_AUTH_TOKEN}
        req = requests.get(base_url, headers=headers)
        self.send_notifications({ "content": content, "file": req.text })

    def deploy(self, event):
        unity_event= request.headers.get("X-UnityCloudBuild-Event")
        try:
            if event in self.unity_events:
                self.unity_events[unity_event](request.get_json(), event.target)
            else:
                self.send_notifications(event + "\n```json\n" + str(request.get_json()) + "```")
        except Exception as e:
            logging.exception(e)
            self.send_notifications("An error occured with the unity cloud build webhook")
