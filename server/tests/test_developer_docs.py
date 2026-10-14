import io
import zipfile
from test_portal import portal, ADMIN


def test_developer_docs_and_kit_are_admin_only(portal):
    _, client, auth, *_ = portal
    for path in ('/admin/api/developer-docs', '/admin/api/developer-kit'):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=auth).status_code == 401
    docs = client.get('/admin/api/developer-docs', headers=ADMIN)
    assert docs.status_code == 200 and {'guide','api','cards','setup','operations','ai','http'} <= set(docs.json())
    result = client.get('/admin/api/developer-kit', headers=ADMIN)
    assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        names=archive.namelist()
        assert 'START-HERE.md' in names and 'server/openapi.json' in names
        assert 'examples/python/notify_bridge.py' in names
        assert all(not n.startswith('/') and '..' not in n.split('/') and '.private' not in n for n in names)
        assert not any(n.endswith('.env') or 'secrets/' in n for n in names)
