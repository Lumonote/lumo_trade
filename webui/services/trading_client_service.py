"""Trading client discovery and jump helpers for the WebUI."""

from __future__ import annotations

import datetime
import json
import os
import plistlib
import platform
import re
import shutil
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Any


DEFAULT_DISCOVERY_TTL = 30


def _format_datetime(ts=None):
    if ts is None:
        return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(ts, (int, float)):
        return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(ts, datetime.datetime):
        return ts.strftime('%Y-%m-%d %H:%M:%S')
    return str(ts)


def _normalize_stock_codes(raw_codes):
    if raw_codes is None:
        return []
    if isinstance(raw_codes, list):
        candidates = raw_codes
    else:
        candidates = re.split(r'[\s,，;；|/]+', str(raw_codes))

    normalized = []
    seen = set()
    for item in candidates:
        token = str(item or '').strip().upper()
        if not token:
            continue
        if token.startswith(('SH', 'SZ', 'BJ')) and len(token) >= 8:
            token = token[2:]
        if token.endswith(('.SH', '.SZ', '.BJ')):
            token = token.split('.')[0]
        match = re.search(r'\d{6}', token)
        if not match:
            continue
        code = match.group(0)
        if code not in seen:
            normalized.append(code)
            seen.add(code)
    return normalized


class TradingClientService:
    def __init__(self, config_path: Path, discovery_ttl: int = DEFAULT_DISCOVERY_TTL):
        self.config_path = Path(config_path)
        self.discovery_ttl = discovery_ttl
        self._cache = {'ts': 0, 'payload': None}

    def discover_clients(self, refresh: bool = False) -> dict[str, Any]:
        return self._discover_trading_clients(refresh=refresh)

    def open_target(self, client_id: str, target: dict[str, Any]) -> dict[str, Any]:
        return self._open_trading_client_target(client_id, target)

    def _load_trading_client_config(self):
        default_config = {
            'discovery': {
                'macos_app_categories': ['public.app-category.finance'],
                'include_all_macos_finance_apps': False,
                'name_keywords': [
                    '股票', '证券', '交易', '行情', '财富', '金融', '同花顺',
                    '通达信', '大智慧', '指南针', '雪球', '富途', '老虎',
                    'futu', 'niuniu', 'tiger', 'tradingview',
                ],
            },
            'jump': {
                'default_mode': 'keyboard',
                'keyboard_delay_ms': 700,
            },
            'adapters': [],
        }
        if not self.config_path.exists():
            return default_config
        try:
            with self.config_path.open('r', encoding='utf-8') as fh:
                loaded = json.load(fh)
        except Exception:
            return default_config

        config = default_config.copy()
        config['discovery'] = {**default_config['discovery'], **loaded.get('discovery', {})}
        config['jump'] = {**default_config['jump'], **loaded.get('jump', {})}
        config['adapters'] = loaded.get('adapters', [])
        return config

    def _slugify_client_id(self, value):
        slug = re.sub(r'[^a-zA-Z0-9_-]+', '-', str(value or '').strip()).strip('-').lower()
        return slug[:80] or 'client'

    def _unique_client_id(self, base, used_ids):
        client_id = self._slugify_client_id(base)
        original = client_id
        idx = 2
        while client_id in used_ids:
            client_id = f'{original}-{idx}'
            idx += 1
        used_ids.add(client_id)
        return client_id

    def _client_match_score(self, client, adapter):
        match = adapter.get('match') or {}
        score = 0
        bundle_id = str(client.get('bundle_id') or '').lower()
        name = str(client.get('name') or '').lower()
        path = str(client.get('path') or '').lower()
        executable = str(client.get('executable') or '').lower()
        schemes = {str(item).lower() for item in client.get('url_schemes') or []}

        if bundle_id and bundle_id in {str(item).lower() for item in match.get('bundle_ids', [])}:
            score += 100
        if schemes.intersection({str(item).lower() for item in match.get('url_schemes', [])}):
            score += 80
        for keyword in match.get('name_keywords', []):
            kw = str(keyword).lower()
            if kw and (kw in name or kw in path or kw in executable):
                score += 25
        for executable_name in match.get('executable_names', []):
            if str(executable_name).lower() in executable:
                score += 35
        return score

    def _match_trading_adapter(self, client, adapters):
        scored = [
            (self._client_match_score(client, adapter), adapter)
            for adapter in adapters
        ]
        scored = [item for item in scored if item[0] > 0]
        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    def _looks_like_trading_client(self, client, config):
        category = str(client.get('category') or '')
        discovery = config.get('discovery', {})
        category_match = category in set(discovery.get('macos_app_categories', []))
        haystack = ' '.join([
            str(client.get('name') or ''),
            str(client.get('path') or ''),
            str(client.get('executable') or ''),
        ]).lower()
        for keyword in discovery.get('name_keywords', []):
            if str(keyword).lower() in haystack:
                return True
        return bool(category_match and discovery.get('include_all_macos_finance_apps'))

    def _macos_read_app_bundle(self, app_path):
        info_path = app_path / 'Contents' / 'Info.plist'
        if not info_path.exists():
            return None
        try:
            with info_path.open('rb') as fh:
                info = plistlib.load(fh)
        except Exception:
            return None

        schemes = []
        for item in info.get('CFBundleURLTypes') or []:
            schemes.extend(item.get('CFBundleURLSchemes') or [])
        executable = info.get('CFBundleExecutable') or app_path.stem
        return {
            'platform': 'macos',
            'name': (
                info.get('CFBundleDisplayName') or
                info.get('CFBundleName') or
                app_path.stem
            ),
            'path': str(app_path),
            'bundle_id': info.get('CFBundleIdentifier') or '',
            'executable': executable,
            'category': info.get('LSApplicationCategoryType') or '',
            'url_schemes': sorted(set(str(item) for item in schemes if item)),
        }

    def _discover_macos_trading_clients(self, config):
        roots = [
            Path('/Applications'),
            Path.home() / 'Applications',
            Path('/System/Applications'),
        ]
        clients = []
        seen_paths = set()
        for root in roots:
            if not root.exists():
                continue
            app_paths = list(root.glob('*.app')) + list(root.glob('*/*.app'))
            for app_path in app_paths:
                resolved = str(app_path.resolve())
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)
                client = self._macos_read_app_bundle(app_path)
                if client and self._looks_like_trading_client(client, config):
                    clients.append(client)
        return clients

    def _discover_windows_trading_clients(self, config):
        clients = []
        adapters = config.get('adapters', [])
        roots = [
            os.environ.get('ProgramFiles'),
            os.environ.get('ProgramFiles(x86)'),
            os.environ.get('LOCALAPPDATA'),
            os.environ.get('APPDATA'),
        ]
        executable_names = set()
        for adapter in adapters:
            executable_names.update(adapter.get('match', {}).get('executable_names', []))
            executable_names.update(adapter.get('windows', {}).get('executable_names', []))
        for name in executable_names:
            path = shutil.which(name)
            if path:
                clients.append({
                    'platform': 'windows',
                    'name': Path(path).stem,
                    'path': path,
                    'bundle_id': '',
                    'executable': Path(path).name,
                    'category': '',
                    'url_schemes': [],
                })

        shortcut_roots = [
            Path(os.environ.get('PROGRAMDATA', '')) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs',
            Path(os.environ.get('APPDATA', '')) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs',
        ]
        for root in shortcut_roots:
            if not root.exists():
                continue
            for path in root.glob('**/*.lnk'):
                client = {
                    'platform': 'windows',
                    'name': path.stem,
                    'path': str(path),
                    'bundle_id': '',
                    'executable': path.name,
                    'category': '',
                    'url_schemes': [],
                }
                if self._looks_like_trading_client(client, config):
                    clients.append(client)

        for root_raw in roots:
            if not root_raw:
                continue
            root = Path(root_raw)
            if not root.exists():
                continue
            for exe_name in executable_names:
                for path in root.glob(f'**/{exe_name}'):
                    if path.is_file():
                        clients.append({
                            'platform': 'windows',
                            'name': path.stem,
                            'path': str(path),
                            'bundle_id': '',
                            'executable': path.name,
                            'category': '',
                            'url_schemes': [],
                        })
        return clients

    def _parse_desktop_entry(self, path):
        data = {}
        try:
            for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
                if '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    data[key.strip()] = value.strip()
        except Exception:
            return None
        exec_cmd = data.get('Exec', '').split()
        return {
            'platform': 'linux',
            'name': data.get('Name') or path.stem,
            'path': str(path),
            'bundle_id': '',
            'executable': exec_cmd[0] if exec_cmd else '',
            'category': data.get('Categories', ''),
            'url_schemes': [
                item.rsplit('/', 1)[-1]
                for item in data.get('MimeType', '').split(';')
                if item.startswith('x-scheme-handler/')
            ],
        }

    def _discover_linux_trading_clients(self, config):
        roots = [
            Path('/usr/share/applications'),
            Path('/usr/local/share/applications'),
            Path.home() / '.local/share/applications',
        ]
        clients = []
        for root in roots:
            if not root.exists():
                continue
            for path in root.glob('*.desktop'):
                client = self._parse_desktop_entry(path)
                if client and self._looks_like_trading_client(client, config):
                    clients.append(client)
        return clients

    def _platform_key(self):
        system = platform.system().lower()
        if system == 'darwin':
            return 'macos'
        if system == 'windows':
            return 'windows'
        if system == 'linux':
            return 'linux'
        return system

    def _platform_trading_clients(self, config):
        system = self._platform_key()
        if system == 'macos':
            return self._discover_macos_trading_clients(config)
        if system == 'windows':
            return self._discover_windows_trading_clients(config)
        if system == 'linux':
            return self._discover_linux_trading_clients(config)
        return []

    def _adapter_templates(self, adapter, platform_key):
        templates = []
        templates.extend(adapter.get('url_templates') or [])
        platform_config = adapter.get(platform_key) or {}
        templates.extend(platform_config.get('url_templates') or [])
        return templates

    def _client_capabilities(self, client, adapter, config):
        platform_key = client.get('platform') or self._platform_key()
        direct_targets = {
            item.get('target')
            for item in self._adapter_templates(adapter or {}, platform_key)
            if item.get('target')
        }
        keyboard_targets = set((adapter or {}).get('keyboard_targets') or [])
        if not keyboard_targets and config.get('jump', {}).get('default_mode') == 'keyboard':
            keyboard_targets = {'stock', 'board', 'search'}
        return {
            'stock': 'stock' in direct_targets or 'stock' in keyboard_targets,
            'board': 'board' in direct_targets or 'board' in keyboard_targets or 'search' in keyboard_targets,
            'direct_targets': sorted(direct_targets),
            'keyboard_targets': sorted(keyboard_targets),
        }

    def _discover_trading_clients(self, refresh=False):
        now = time.time()
        if (
            not refresh and
            self._cache.get('payload') and
            now - self._cache.get('ts', 0) < self.discovery_ttl
        ):
            return self._cache['payload']

        config = self._load_trading_client_config()
        adapters = config.get('adapters', [])
        used_ids = set()
        clients = []
        seen = set()
        for client in self._platform_trading_clients(config):
            key = (client.get('platform'), client.get('bundle_id'), client.get('path'))
            if key in seen:
                continue
            seen.add(key)
            adapter = self._match_trading_adapter(client, adapters) or {}
            adapter_id = adapter.get('id') or client.get('bundle_id') or client.get('name')
            client_id = self._unique_client_id(adapter_id, used_ids)
            capabilities = self._client_capabilities(client, adapter, config)
            client.update({
                'id': client_id,
                'display_name': adapter.get('display_name') or client.get('name'),
                'adapter_id': adapter.get('id') or '',
                'capabilities': capabilities,
                'jump_mode': (adapter.get('jump') or {}).get('mode') or config.get('jump', {}).get('default_mode', 'keyboard'),
            })
            if capabilities.get('stock') or capabilities.get('board'):
                clients.append(client)

        payload = {
            'platform': self._platform_key(),
            'clients': sorted(clients, key=lambda item: item.get('display_name') or item.get('name') or ''),
            'config_path': str(self.config_path),
            'generated_at': _format_datetime(now),
        }
        self._cache['payload'] = payload
        self._cache['ts'] = now
        return payload

    def _market_prefix_for_code(self, stock_code):
        code = str(stock_code or '').strip()
        if code.startswith(('43', '83', '87', '92')):
            return {'lower': 'bj', 'upper': 'BJ', 'ths_market': '48'}
        if code.startswith(('6', '9')):
            return {'lower': 'sh', 'upper': 'SH', 'ths_market': '17'}
        return {'lower': 'sz', 'upper': 'SZ', 'ths_market': '33'}

    def _template_context(self, target):
        stock_code = _normalize_stock_codes(target.get('stock_code') or target.get('code'))
        code = stock_code[0] if stock_code else ''
        board_code = str(target.get('board_code') or '').strip().upper()
        board_name = str(target.get('board_name') or target.get('sector') or target.get('name') or '').strip()
        stock_name = str(target.get('stock_name') or target.get('name') or '').strip()
        query = code or board_code or board_name or stock_name
        market = self._market_prefix_for_code(code)
        return {
            'code': code,
            'stock_code': code,
            'stock_name': stock_name,
            'board_code': board_code,
            'board_name': board_name,
            'query': query,
            'market': market['lower'],
            'market_upper': market['upper'],
            'ths_market': market['ths_market'],
        }

    def _render_jump_template(self, template, context):
        try:
            return str(template).format(**{
                key: urllib.parse.quote(str(value), safe='')
                for key, value in context.items()
            })
        except KeyError:
            return ''

    def _run_detached(self, args):
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    def _launch_client_app(self, client):
        system = client.get('platform') or self._platform_key()
        path = client.get('path') or ''
        if system == 'macos':
            if path.endswith('.app'):
                return self._run_detached(['open', path])
            return self._run_detached(['open', '-a', client.get('display_name') or client.get('name') or path])
        if system == 'windows':
            if path and hasattr(os, 'startfile'):
                os.startfile(path)
                return True
            return self._run_detached([path]) if path else False
        if system == 'linux':
            executable = client.get('executable') or path
            return self._run_detached([executable]) if executable else False
        return False

    def _applescript_string(self, value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'

    def _send_keyboard_jump(self, client, query, delay_ms):
        if not query:
            return False, '缺少可跳转的代码或名称'
        system = client.get('platform') or self._platform_key()
        self._launch_client_app(client)
        delay_seconds = max(float(delay_ms or 700) / 1000, 0.1)

        if system == 'macos':
            app_name = client.get('name') or client.get('display_name')
            app_target = (
                f'id {self._applescript_string(client.get("bundle_id"))}'
                if client.get('bundle_id')
                else self._applescript_string(app_name)
            )
            script = [
                f'tell application {app_target} to activate',
                f'delay {delay_seconds:.2f}',
                'tell application "System Events"',
                f'keystroke {self._applescript_string(query)}',
                'key code 36',
                'end tell',
            ]
            args = ['osascript']
            for line in script:
                args.extend(['-e', line])
            completed = subprocess.run(args, capture_output=True, text=True, timeout=5)
            if completed.returncode == 0:
                return True, '已通过客户端快捷输入跳转'
            message = (completed.stderr or completed.stdout or '').strip()
            return False, message or '系统未允许键盘自动化'

        if system == 'windows':
            ps_query = str(query).replace("'", "''")
            command = (
                f"Start-Sleep -Milliseconds {int(delay_seconds * 1000)}; "
                "Add-Type -AssemblyName System.Windows.Forms; "
                f"[System.Windows.Forms.SendKeys]::SendWait('{ps_query}{{ENTER}}')"
            )
            completed = subprocess.run(
                ['powershell', '-NoProfile', '-Command', command],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if completed.returncode == 0:
                return True, '已通过客户端快捷输入跳转'
            return False, (completed.stderr or completed.stdout or '').strip() or '键盘自动化失败'

        if system == 'linux':
            xdotool = shutil.which('xdotool')
            if not xdotool:
                return False, '未安装 xdotool，已尝试启动客户端'
            completed = subprocess.run(
                [xdotool, 'type', '--delay', '20', str(query)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if completed.returncode == 0:
                subprocess.run([xdotool, 'key', 'Return'], capture_output=True, timeout=2)
                return True, '已通过客户端快捷输入跳转'
            return False, (completed.stderr or completed.stdout or '').strip() or '键盘自动化失败'

        return False, '当前系统暂不支持键盘跳转'

    def _open_trading_client_target(self, client_id, target):
        discovered = self._discover_trading_clients(refresh=True)
        config = self._load_trading_client_config()
        client = next((item for item in discovered['clients'] if item['id'] == client_id), None)
        if not client:
            return {'success': False, 'error': '未发现该交易客户端'}

        adapters = config.get('adapters', [])
        adapter = self._match_trading_adapter(client, adapters) or {}
        target_type = str(target.get('type') or '').strip() or ('stock' if target.get('stock_code') else 'board')
        context = self._template_context(target)

        for item in self._adapter_templates(adapter, client.get('platform') or self._platform_key()):
            if item.get('target') != target_type:
                continue
            url = self._render_jump_template(item.get('url') or '', context)
            if not url:
                continue
            if client.get('platform') == 'macos' and client.get('bundle_id'):
                self._run_detached(['open', '-b', client['bundle_id'], url])
            elif client.get('platform') == 'windows' and hasattr(os, 'startfile'):
                os.startfile(url)
            else:
                self._run_detached(['open', url] if client.get('platform') == 'macos' else ['xdg-open', url])
            return {
                'success': True,
                'mode': 'scheme',
                'client': client.get('display_name'),
                'target': context['query'],
                'message': f"已打开 {client.get('display_name') or client.get('name') or '交易客户端'} 并跳转 {context['query']}",
            }

        delay_ms = config.get('jump', {}).get('keyboard_delay_ms', 700)
        success, message = self._send_keyboard_jump(client, context['query'], delay_ms)
        return {
            'success': success,
            'mode': 'keyboard',
            'client': client.get('display_name'),
            'target': context['query'],
            'message': message,
        }
