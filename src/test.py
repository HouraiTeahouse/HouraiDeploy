import pycurl, sys, os, tempfile, hashlib, json, time, subprocess, re
from util import namedtuple_from_mapping
from zipfile import ZipFile
from collections import OrderedDict

with open('/var/htwebsite/deploy_config.json', 'r') as config_file:
    config = namedtuple_from_mapping(json.load(config_file))

PLATFORM = 'Linux'
PROJECT = 'fantasy-crescendo'

vars_regex = re.compile('{(.*?)}')
prefix_regex = re.compile('{base_url}/?')


def build_path(path_format, vars_obj):
    matches = vars_regex.findall(path_format)
    path = path_format
    for match in matches:
        target = '{%s}' % match
        print(target)
        print(match)
        if isinstance(vars_obj, dict) and match in vars_obj:
            path = path.replace(target, str(vars_dict[match]))
        else:
            replacement = getattr(vars_obj, match, None)
            if replacement is not None:
                path = path.replace(target, str(replacement))
        print(path)
    return path


def hash_file(filepath, block_size=65536):
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as file_source:
        for block in iter(lambda: file_source.read(block_size), b''):
            hasher.update(block)
    return hasher.hexdigest()


def create_file_summary(filepath):
    return {
        "size": os.path.getsize(filepath),
        "sha256": hash_file(filepath)
    }

DEPLOY_DIR = 'deploy'

def download_file(url, path):
    with open(path, 'wb') as target_file:
        curl = pycurl.Curl()
        curl.setopt(curl.URL, url)
        curl.setopt(curl.WRITEDATA, target_file)
        curl.perform()
        curl.close()


def unzip_to_dir(file_path, dst_dir):
    with ZipFile(file_path) as zip_file:
        zip_file.extractall(path=dst_dir)


def deploy_from_url(event):
    tempdir = tempfile.TemporaryDirectory()
    temp_dir = tempdir.name

    zip_path = os.path.join(temp_dir, 'build.zip')
    print('Downloading ZIP File to %s' % zip_path)
    download_file(event.download_url, zip_path)

    temp_data_dir = os.path.join(temp_dir, 'data')
    print('Unzipping ZIP file to: %s' % temp_data_dir)
    os.makedirs(temp_data_dir)
    unzip_to_dir(zip_path, temp_data_dir)
    os.remove(zip_path)
    abs_dir_path = os.path.abspath(temp_data_dir)

    if 'PROJECTS' in config._asdict() and PROJECT in config.PROJECTS:
        json_index = OrderedDict(config.PROJECTS[PROJECT])
    else:
        json_index = OrderedDict()

    json_index['base_url'] = event.base_url
    json_index['project'] = event.project
    json_index['branch'] = event.branch
    json_index['platform'] = event.platform
    json_index['last_updated'] = int(time.time())
    files = OrderedDict()
    for directory, _, dir_files in os.walk(abs_dir_path):
        for file in dir_files:
            full_path = os.path.join(directory, file)
            relative_path = full_path.replace(abs_dir_path + os.path.sep, '')
            summary = create_file_summary(full_path)

            # Append the hash of the file to its filename to cache bust
            os.rename(full_path, full_path + '_' + summary['sha256'])
            files[relative_path] = summary

    json_index["files"] = files
    with open(os.path.join(temp_data_dir, 'index.json'), 'w') as index:
        json.dump(json_index, index, indent=4)

    dest_dir = prefix_regex.sub(event.base_dir, event.url_format)
    print(dest_dir)
    dest_dir = build_path(dest_dir, event)
    print(os.path.abspath(dest_dir))
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir)
    print('Moving completed files from %s to %s' % (temp_data_dir, dest_dir))
    # Forcibly move and replace files. This should be an atomic change
    subprocess.call('cp -Trf %s %s' % (temp_data_dir, dest_dir), shell=True)

    tempdir.cleanup()


class Test():

    def __init__(self):
        self.url_format = '{base_url}/{project}/{branch}/{platform}'
        self.base_url = 'https://patch.houraiteahouse.net'
        self.download_url = sys.argv[1]
        self.project = PROJECT
        self.branch = 'master'
        self.platform = 'Linux'
        self.base_dir = '/var/www/htfrontend/patch/'

test = Test()
deploy_from_url(test)
