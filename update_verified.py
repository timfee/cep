import json
import re
import requests

wf = json.load(open('workflow.json'))

# Fetch metadata texts
graph_v1 = requests.get('https://raw.githubusercontent.com/microsoftgraph/msgraph-metadata/master/openapi/v1.0/openapi.yaml').text
graph_beta = requests.get('https://raw.githubusercontent.com/microsoftgraph/msgraph-metadata/master/openapi/beta/openapi.yaml').text
ci = requests.get('https://cloudidentity.googleapis.com/$discovery/rest?version=v1').json()
dir_api = requests.get('https://admin.googleapis.com/$discovery/rest?version=directory_v1').json()

# Build google method map
cloud_paths = {}
for res in ci.get('resources', {}).values():
    for m in res.get('methods', {}).values():
        cloud_paths[(m['path'], m['httpMethod'])] = True
for res in dir_api.get('resources', {}).values():
    for m in res.get('methods', {}).values():
        cloud_paths[(m['path'], m['httpMethod'])] = True


def regex_from_template(t):
    t = t.strip('/').split('?')[0]
    t = re.sub(r'\{[^}]+\}', '[^/]+', t)
    return t + '$'


def check_google(path, method):
    for (tmpl, http_method) in cloud_paths.keys():
        if http_method == method and re.search(regex_from_template(tmpl), path.strip('/')):
            return True
    return False


def check_graph(path, method, beta=False):
    spec = graph_beta if beta else graph_v1
    if path.startswith('/v1.0/'):
        path = path[5:]
    template = re.sub(r'\{[^}]+\}', '{var}', path.strip('/').split('?')[0])
    pattern = re.escape(template).replace('{var}', '[^/]+')
    regex = rf"'{pattern}':\n\s*{method.lower()}:"
    return re.search(regex, spec, re.IGNORECASE) is not None

for step in wf['steps']:
    calls = (step.get('verify') or []) + (step.get('execute') or [])
    if isinstance(calls, dict):
        calls = [calls]
    verified = True
    if not calls:
        verified = True
    else:
        for data in calls:
            method = data.get('method', 'GET').upper()
            path = data['path']
            ok = False
            if path.startswith('http'):
                ok = True
            elif path.startswith('/beta/'):
                ok = check_graph(path[5:], method, beta=True)
            elif path.startswith('/v1.0/'):
                ok = check_graph(path, method, beta=False)
            elif path.startswith('/admin') or path.startswith('/v1'):
                ok = check_google(path, method)
            else:
                ok = check_graph(path, method) or check_google(path, method)
            if not ok:
                verified = False
                break
    step['verifiedByCodex'] = bool(verified)

json.dump(wf, open('workflow.json', 'w'), indent=2)
