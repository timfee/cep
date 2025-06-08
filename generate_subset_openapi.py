import json, yaml, requests, sys

workflow = json.load(open('workflow.json'))

# gather unique (path, method)
ops = set()
for step in workflow['steps']:
    for k in ['verify', 'execute']:
        data = step.get(k)
        if not data:
            continue
        if isinstance(data, dict):
            data = [data]
        for call in data:
            path = call['path']
            method = call.get('method', 'GET').upper()
            if not path.startswith('http'):
                ops.add((path, method))

# fetch official specs
print('Fetching Google discovery...')
admin = requests.get('https://admin.googleapis.com/$discovery/rest?version=directory_v1').json()
cloud = requests.get('https://cloudidentity.googleapis.com/$discovery/rest?version=v1').json()
print('Fetching Microsoft Graph openapi...')
openapi_v1 = requests.get('https://raw.githubusercontent.com/microsoftgraph/msgraph-metadata/master/openapi/v1.0/openapi.yaml').text
openapi_beta = requests.get('https://raw.githubusercontent.com/microsoftgraph/msgraph-metadata/master/openapi/beta/openapi.yaml').text
spec_v1 = yaml.safe_load(openapi_v1)
spec_beta = yaml.safe_load(openapi_beta)

def select_google(api):
    selected = {}
    def walk(res, base=''):
        if 'methods' in res:
            for name, m in res['methods'].items():
                p = '/' + res.get('path', '').lstrip('/') if 'path' in res else ''
                path = (m['path']) if m['path'].startswith('/') else '/' + m['path']
                selected.setdefault(path, {})[m['httpMethod']] = m
        if 'resources' in res:
            for sub in res['resources'].values():
                walk(sub)
    walk(api)
    return selected

def select_graph(spec):
    selected = {}
    paths = spec.get('paths', {})
    for path, defs in paths.items():
        for method, op in defs.items():
            m = method.upper()
            selected.setdefault(path, {})[m] = op
    return selected

google_map = {**select_google(admin), **select_google(cloud)}
graph_v1_map = select_graph(spec_v1)
graph_beta_map = select_graph(spec_beta)

subset = {"openapi": "3.0.0", "paths": {}}

for path, method in ops:
    entry = None
    if path.startswith('/v1.0/'):
        p = path[5:]
        entry = graph_v1_map.get(p, {}).get(method)
    elif path.startswith('/beta/'):
        p = path[5:]
        entry = graph_beta_map.get(p, {}).get(method)
    elif path.startswith('/admin') or path.startswith('/v1'):
        entry = google_map.get(path, {}).get(method)
    else:
        entry = graph_v1_map.get(path, {}).get(method) or graph_beta_map.get(path, {}).get(method)
    if entry:
        subset['paths'].setdefault(path, {})[method.lower()] = entry

with open('openapi_subset.json', 'w') as f:
    json.dump(subset, f, indent=2)
print('Wrote openapi_subset.json with', len(subset['paths']), 'operations')
