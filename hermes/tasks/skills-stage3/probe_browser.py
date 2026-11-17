"""Open Test's existing pilot chat in an isolated Chromium profile."""
import json
from pathlib import Path
import subprocess
from playwright.sync_api import sync_playwright

UID = '695924f7-9a9b-4ba4-bc54-a5bc2a440d56'
CHAT = '2ecf6a5a-8ff6-44b4-bf66-a37c9c81d2a2'
CHROME = '/root/.hermes/tools/chromium-1208/chrome-linux64/chrome'
OUT = Path('/root/.hermes/cache/scratch/skills-test-browser.png')
script = """import asyncio
from datetime import timedelta
from open_webui.models.auths import Auths
from open_webui.utils.auth import create_token
async def main():
 a=await Auths.get_auth_by_id('695924f7-9a9b-4ba4-bc54-a5bc2a440d56')
 print(create_token({'id':a.id,'session_stamp':a.session_stamp},expires_delta=timedelta(minutes=10)))
asyncio.run(main())
"""
r = subprocess.run(['docker', 'exec', '-i', '-w', '/app/backend', 'open-webui', 'python', '-'], input=script, capture_output=True, text=True, check=True)
token = r.stdout.strip().splitlines()[-1]
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME, headless=True, args=['--no-sandbox'])
    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1)
    context.add_init_script('localStorage.setItem("token", ' + json.dumps(token) + ')')
    context.add_cookies([{'name': 'token', 'value': token, 'url': 'https://ai.esmien.ru'}])
    page = context.new_page()
    page.goto('https://ai.esmien.ru/c/' + CHAT, wait_until='domcontentloaded', timeout=60000)
    page.get_by_text('inspect-json', exact=False).first.wait_for(state='visible', timeout=60000)
    text = page.locator('body').inner_text()
    print('Correct chat path:', '/c/' + CHAT in page.url)
    print('Fixture name visible:', 'inspect-json' in text)
    print('Prompt visible:', 'перечисли их точные имена' in text)
    print('Model label deepseek visible:', 'deepseek' in text.lower())
    page.screenshot(path=str(OUT), full_page=False)
    print('Screenshot:', OUT)
    page.get_by_text('Explored', exact=False).first.click()
    page.wait_for_timeout(500)
    expanded = page.locator('body').inner_text()
    print('Expanded tool call shows function:', 'list_personal_skills' in expanded)
    print('Expanded tool output contains fixture:', 'inspect-json' in expanded)
    page.screenshot(path='/root/.hermes/cache/scratch/skills-test-browser-expanded.png', full_page=False)
    browser.close()
