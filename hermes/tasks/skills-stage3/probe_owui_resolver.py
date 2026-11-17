"""Exercise the installed pilot through Open WebUI's actual tool resolver."""
import asyncio
import json
from starlette.requests import Request
from open_webui.main import app
from open_webui.models.users import Users
from open_webui.utils.tools import get_tools

TEST = '695924f7-9a9b-4ba4-bc54-a5bc2a440d56'
OTHER = '203ace4e-bc84-43c8-9c5e-92dc9e533162'
TOOL = 'personal_skill_catalog_pilot'


async def main():
    request = Request({'type': 'http', 'method': 'POST', 'path': '/', 'headers': [], 'app': app, 'query_string': b''})
    test = await Users.get_user_by_id(TEST)
    other = await Users.get_user_by_id(OTHER)
    assert test and other and test.role == other.role == 'user'
    allowed = await get_tools(request, [TOOL], test, {'__user__': {'id': test.id}})
    denied = await get_tools(request, [TOOL], other, {'__user__': {'id': other.id}})
    assert not denied, 'unrelated user has access'
    assert list(allowed) == ['list_personal_skills'], list(allowed)
    assert not allowed['list_personal_skills']['spec']['parameters']['properties']
    result = json.loads(await allowed['list_personal_skills']['callable']())
    assert [x['name'] for x in result['skills']] == ['inspect-json'], result
    print('PASS: actual OWUI resolver executes Test pilot and returns inspect-json')
    print('PASS: other ordinary user is denied; user ID not exposed as model parameter')

asyncio.run(main())
