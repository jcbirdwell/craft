import json
from typing import Literal
import requests

DEFAULT_FACETS = json.dumps([["categories:neoforge"],["versions:1.21.1"],["project_type:mod"]])



class ModrinthAPI:
    BASE_API = 'https://api.modrinth.com/v2'
    def __init__(self, token):
        self.token = token

    @property
    def headers(self):
        return {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': self.token
        }

    def _api(self,
             method: Literal['get', 'post'],
             endpoint: str,
             params: dict | None = None,
             payload: dict | None = None
             ):
        url = f'{self.BASE_API}/{endpoint.removeprefix('/')}'
        resp = requests.request(
            method=method,
            url=url,
            params=params,
            json=payload,
            headers=self.headers
        )
        if resp.status_code >= 400:
            return None
        return resp.json()

    def get(self, endpoint: str, params=None):
        return self._api('get', endpoint=endpoint, params=params)

    def post(self, endpoint: str, params=None, data=None):
        return self._api('post', endpoint, params=params, payload=data)

    def match(self, sha1_hex: str):
        return self.get(f'version_file/{sha1_hex}', params={'algorithm': 'sha1', 'multiple': False})

    def project(self, project_id: str):
        return self.get(f'project/{project_id}')

    def search(self,
               query: str,
               facets=DEFAULT_FACETS,
               index='relevance',
               offset=0,
               limit=20
               ):
        limit = min(100, limit)
        return self.get('search', params={
            'query': query,
            'facets': facets,
            'index': index,
            'offset': offset,
            'limit': limit
        })

    @staticmethod
    def project_env(mrp):
        if mrp['server_side'] == 'unsupported':
            return 'client_only'
        elif mrp['client_side'] == 'unsupported':
            return 'server_only'
        else:
            return 'both'

    def releases(self, project_id, loader='neoforge', mc_version='1.21.1'):
        return self.get(f'project/{project_id}/version', params={
            'loaders': json.dumps([loader]),
            'game_versions': json.dumps([mc_version])
        })


class CurseAPI:
    BASE_API = 'https://api.curseforge.com/v1'
    loaders = {
        0: 'any',
        1: 'forge',
        2: 'cauldron',
        3: 'liteloader',
        4: 'fabric',
        5: 'quilt',
        6: 'neoforge',
    }
    flip_loaders = {v: k for k, v in loaders.items()}

    def __init__(self, token):
        self.token = token

    @property
    def headers(self):
        return {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'x-api-key': self.token
        }

    def _api(self,
             method: Literal['get', 'post'],
             endpoint: str,
             params: dict | None = None,
             payload: dict | None = None,
             retries=1
             ):
        url = f'{self.BASE_API}/{endpoint.removeprefix('/')}'
        print(f'curse api request {url}')
        resp = requests.request(
            method=method,
            url=url,
            params=params,
            json=payload,
            headers=self.headers
        )
        sc = resp.status_code
        if sc >= 500 or sc == 429:
            if retries > 0:
                return self._api(method, endpoint, params, payload, retries-1)
            print(f'bad resp [{sc}] {vars(resp)}')
            return None
        elif sc >= 400:
            print(f'bad resp [{sc}] {vars(resp)}')
            return None
        return resp.json()['data']


    def get(self, endpoint: str, params=None):
        return self._api('get', endpoint=endpoint, params=params)

    def post(self, endpoint: str, params=None, data=None):
        return self._api('post', endpoint, params=params, payload=data)

    def matches(self, fingerprints: list[int] | int):
        if isinstance(fingerprints, int):
            fingerprints = [fingerprints]
        return self.post('fingerprints', data={'fingerprints': fingerprints})

    def match(self, fingerprint: int):
        return next((z for z in self.matches(fingerprint)['exactMatches']), None)

    def project(self, project_id: int):
        return self.get(f'mods/{project_id}')

    @staticmethod
    def project_type(project):
        match project['classId']:
            case 6:
                # case 5299:
                return 'mod'
            case 6552:
                # case 6554:
                return 'shader'
            case 12:
                # case 393:
                return 'texture'
            case 6945:
                # case 6948:
                return 'data'

        raise ValueError('unknown')

    def releases(self, project_id, loader='neoforge', mc_version='1.21.1'):
        return self.get(f'mods/{project_id}/files', params={
            'gameVersion': mc_version,
            'modLoaderType': self.flip_loaders[loader]
        })

