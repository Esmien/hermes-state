"""Attempt a real Test-user chat with the private pilot; no credentials logged."""
import asyncio
from datetime import timedelta
import json
import uuid

import aiohttp
import socketio
from open_webui.models.auths import Auths
from open_webui.utils.auth import create_token

UID = '695924f7-9a9b-4ba4-bc54-a5bc2a440d56'
MODEL = 'chat.deepseek/deepseek-v4.1-flash'
TOOL = 'personal_skill_catalog_pilot'
BASE = 'http://127.0.0.1:8080'


async def main():
    auth = await Auths.get_auth_by_id(UID)
    if auth is None or not auth.session_stamp:
        raise RuntimeError('Test session identity unavailable')
    token = create_token({'id': UID, 'session_stamp': auth.session_stamp}, expires_delta=timedelta(minutes=10))
    headers = {'Authorization': 'Bearer ' + token}
    sio = socketio.AsyncClient(logger=False, engineio_logger=False)
    events = []
    @sio.on('chat-events')
    async def chat_events(data):
        events.append(data)
    async with aiohttp.ClientSession(headers=headers) as http:
        async with http.get(BASE + '/api/v1/auths/') as response:
            profile = await response.json()
            if response.status != 200 or profile.get('id') != UID:
                raise RuntimeError('Test session not accepted')
        await sio.connect(BASE, auth={'token': token}, socketio_path='ws/socket.io', transports=['websocket'])
        try:
            sid = sio.get_sid('/')
            prompt = 'Используй доступный инструмент личных скиллов и перечисли их точные имена. Не выдумывай.'
            mid, aid = str(uuid.uuid4()), str(uuid.uuid4())
            msg = {'id': mid, 'role': 'user', 'content': prompt, 'parentId': None, 'childrenIds': [aid], 'models': [MODEL]}
            assistant = {'id': aid, 'role': 'assistant', 'content': '', 'parentId': mid, 'childrenIds': [], 'model': MODEL, 'done': False}
            chat = {'id': '', 'title': 'Тест каталога скиллов', 'models': [MODEL], 'params': {}, 'messages': [msg, assistant], 'history': {'messages': {mid: msg, aid: assistant}, 'currentId': aid}, 'tags': []}
            async with http.post(BASE + '/api/v1/chats/new', json={'chat': chat}) as response:
                item = await response.json()
                if response.status != 200:
                    raise RuntimeError('Chat creation failed: HTTP ' + str(response.status))
                chat_id = item['id']
            body = {'stream': True, 'model': MODEL, 'messages': [{'role': 'user', 'content': prompt}], 'chat_id': chat_id, 'id': aid, 'session_id': sid, 'tool_ids': [TOOL], 'features': {'web_search': False, 'image_generation': False, 'code_interpreter': False}}
            async with http.post(BASE + '/api/chat/completions', json=body) as response:
                if response.status != 200:
                    raise RuntimeError('Completion request failed: HTTP ' + str(response.status))
                await response.read()
            found = False
            for _ in range(45):
                await asyncio.sleep(2)
                async with http.get(BASE + '/api/v1/chats/' + chat_id) as response:
                    if response.status != 200:
                        raise RuntimeError('Chat readback failed: HTTP ' + str(response.status))
                    result = await response.json()
                content = json.dumps(result.get('chat', {}).get('history', {}).get('messages', {}).get(aid, {}), ensure_ascii=False)
                if 'list_personal_skills' in content and 'inspect-json' in content:
                    found = True
                    break
            print('Test chat id:', chat_id)
            print('Tool call and real fixture name in persisted response:', found)
            print('Socket events received:', len(events))
            if not found:
                raise RuntimeError('Did not observe tool invocation plus result in persisted chat')
        finally:
            await sio.disconnect()

asyncio.run(main())
