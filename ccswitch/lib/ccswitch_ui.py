"""Terminal-only input and the slot draft wizard. No persistence or application."""
import getpass
import os
import select
import shutil
import sys
import termios
import unicodedata
from urllib.parse import urlsplit
from ccswitch_profiles import extract_settings, redact
from ccswitch_slots import MODEL_BINDINGS, SLOTS, edit_menu, set_slot, unify_slots


class Cancelled(Exception):
    pass


def require_terminal():
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ValueError('Interactive input requires stdin and stdout terminals; specify a name and --from file')


class Back(Cancelled):
    pass


def ask(prompt, *, secret=False):
    require_terminal()
    try:
        if secret:
            value = getpass.getpass(prompt)
        else:
            value = _read_text(prompt)
    except (EOFError, KeyboardInterrupt):
        raise Cancelled() from None
    if value.strip().lower() in ('cancel', 'quit'):
        raise Back()
    return value


def _escape_sequence(fd):
    sequence = b''
    while select.select([fd], [], [], .08)[0]:
        char = os.read(fd, 1)
        if not char:
            break
        sequence += char
        if sequence in (b'[A', b'[B', b'[C', b'[D', b'OA', b'OB', b'OC', b'OD',
                        b'[H', b'[F', b'OH', b'OF') or sequence.endswith(b'~'):
            break
        if len(sequence) >= 8:
            break
    return sequence


def _read_text(prompt):
    # fd reads avoid buffering keys intended for the next menu. Noncanonical
    # input also lets bare Esc return immediately without waiting for Enter.
    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    mode = termios.tcgetattr(fd)
    mode[3] &= ~(termios.ECHO | termios.ICANON | termios.ISIG)
    mode[6][termios.VMIN] = 1
    mode[6][termios.VTIME] = 0
    raw, old_width = bytearray(), 0

    def width(text):
        return sum(0 if unicodedata.combining(c) else
                   (2 if unicodedata.east_asian_width(c) in 'WF' else 1) for c in text)

    def draw():
        nonlocal old_width
        columns = shutil.get_terminal_size((80, 24)).columns
        prefix = _screen_text(prompt, max(1, columns // 2))
        value = raw.decode('utf-8', errors='ignore')
        available = max(1, columns - width(prefix) - 1)
        while value and width(value) > available:
            value = value[1:]
        text = prefix + value
        clear = ('\r' + ' ' * old_width + '\r') if os.environ.get('TERM') == 'dumb' else '\r\x1b[K'
        sys.stdout.write(clear + text)
        sys.stdout.flush()
        old_width = width(text)

    try:
        termios.tcsetattr(fd, termios.TCSANOW, mode)
        draw()
        while True:
            char = os.read(fd, 1)
            if not char or char in (b'\x03', b'\x04'):
                raise Cancelled()
            if char in (b'\n', b'\r'):
                return raw.decode('utf-8')
            if char == b'\x1b':
                if not _escape_sequence(fd):
                    raise Back()
            elif char in (b'\x7f', b'\x08'):
                raw[:] = raw.decode('utf-8', errors='ignore')[:-1].encode()
            elif char == b'\x15':
                raw.clear()
            elif char >= b' ':
                raw.extend(char)
            draw()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)
        print(flush=True)


def _screen_text(value, width):
    result, used = [], 0
    for char in str(value):
        if unicodedata.category(char).startswith('C'):
            continue
        size = 0 if unicodedata.combining(char) else (2 if unicodedata.east_asian_width(char) in 'WF' else 1)
        if used + size > width:
            break
        result.append(char)
        used += size
    return ''.join(result)


def choose(title, choices, *, default=None, allow_custom=False):
    """Select a value with arrows. Plain terminals also accept numbered input."""
    require_terminal()
    if not choices:
        raise ValueError('No choices available')
    index = next((i for i, (key, _) in enumerate(choices) if key == default), 0)

    def resolve(value):
        if not value:
            return True, choices[index][0]
        if value.lower() in ('cancel', 'quit'):
            raise Back()
        if value.isdigit() and 1 <= int(value) <= len(choices):
            return True, choices[int(value) - 1][0]
        for key, _ in choices:
            if isinstance(key, str) and key == value:
                return True, key
        return (True, value) if allow_custom else (False, None)

    if os.environ.get('TERM') == 'dumb':
        while True:
            print(title)
            for number, (_, label) in enumerate(choices, 1):
                print(str(number) + '. ' + label + (' [默认]' if number - 1 == index else ''))
            valid, value = resolve(ask('选择编号（回车选默认，cancel 返回）: ').strip())
            if valid:
                return value
            print('请选择列表中的一项。')

    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    mode = termios.tcgetattr(fd)
    mode[3] &= ~(termios.ECHO | termios.ICANON | termios.ISIG)
    mode[6][termios.VMIN] = 1
    mode[6][termios.VTIME] = 0
    lines, typed = 0, bytearray()

    def draw():
        nonlocal lines
        columns, rows = shutil.get_terminal_size((80, 24))
        capacity = max(1, rows - 4)
        start = min(max(0, index - capacity // 2), max(0, len(choices) - capacity))
        if lines:
            sys.stdout.write('\x1b[' + str(lines) + 'A\r\x1b[J')
        rows_out = [title]
        for position in range(start, min(len(choices), start + capacity)):
            rows_out.append(('> ' if position == index else '  ') + choices[position][1])
        rows_out.append('↑/↓ 选择 · Enter 确认 · Esc 返回  (' + str(index + 1) + '/' + str(len(choices)) + ')')
        if typed:
            rows_out.append('输入: ' + typed.decode('utf-8', errors='replace'))
        for row in rows_out:
            print(_screen_text(row, max(1, columns - 1)))
        sys.stdout.flush()
        lines = len(rows_out)

    try:
        termios.tcsetattr(fd, termios.TCSANOW, mode)
        sys.stdout.write('\x1b[?25l')
        draw()
        while True:
            char = os.read(fd, 1)
            if not char or char in (b'\x03', b'\x04'):
                raise Cancelled()
            if char == b'\x1b':
                sequence = _escape_sequence(fd)
                if not sequence:
                    raise Back()
                if sequence in (b'[A', b'OA'):
                    index = (index - 1) % len(choices)
                elif sequence in (b'[B', b'OB'):
                    index = (index + 1) % len(choices)
                elif sequence in (b'[H', b'OH', b'[1~', b'[7~'):
                    index = 0
                elif sequence in (b'[F', b'OF', b'[4~', b'[8~'):
                    index = len(choices) - 1
                elif sequence == b'[5~':
                    index = max(0, index - 5)
                elif sequence == b'[6~':
                    index = min(len(choices) - 1, index + 5)
                typed.clear()
            elif char in (b'\n', b'\r'):
                valid, value = resolve(typed.decode('utf-8', errors='replace').strip())
                if valid:
                    return value
                typed.clear()
            elif char in (b'\x7f', b'\x08'):
                typed[:] = typed.decode('utf-8', errors='ignore')[:-1].encode()
            elif char >= b' ':
                typed.extend(char)
            draw()
    except KeyboardInterrupt:
        raise Cancelled() from None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)
        sys.stdout.write('\x1b[?25h')
        sys.stdout.flush()


def preview(value, target=None, *, compact=False):
    public = redact(value)
    settings = public.get('settings', public)
    env = settings.get('env', {})
    if public.get('name'):
        print('Profile: ' + public['name'])
    auth = public.get('auth_type') or ('api_key' if env.get('ANTHROPIC_API_KEY') else
                                      'bearer_token' if env.get('ANTHROPIC_AUTH_TOKEN') else 'incomplete')
    # Show only the host: endpoint userinfo, paths and query strings may be private.
    try:
        host = urlsplit(env.get('ANTHROPIC_BASE_URL', '')).hostname or '(unset)'
    except ValueError:
        host = '(invalid URL)'
    print('Connection: ' + host + ' | ' + auth)
    mappings = [(slot, env.get(key)) for slot, key in SLOTS.items()]
    if not env.get(SLOTS['startup']) and settings.get('model'):
        mappings.append(('startup', settings['model']))
    models = ', '.join(slot + '=' + model for slot, model in mappings if model)
    if not compact:
        print('Models: ' + (models or '(not configured)'))
    print('Menu: ' + str(len(settings.get('modelPicker', {}).get('options', []))) + ' custom entries')
    if target is not None:
        print('Global target: ' + str(target))


def pick_profile(profiles, title='选择配置'):
    if not profiles:
        raise ValueError('No saved profiles; add or import a profile first')
    return choose(title, [(p['name'], p['name']) for p in profiles])


def select_profile(profiles, target):
    if not profiles:
        raise ValueError('No saved profiles; add or import a profile first')
    remove = object()
    selected = choose('选择配置', [(p['name'], p['name']) for p in profiles] +
                      [(remove, '删除配置…')])
    if selected is remove:
        return 'remove', select_profile_for_removal(profiles, target)
    preview(next(p for p in profiles if p['name'] == selected), target)
    if choose('确认应用到以上全局配置？', [('n', '取消'), ('y', '确认应用')]) != 'y':
        raise Cancelled()
    return 'use', selected


def select_profile_for_removal(profiles, target):
    selected = pick_profile(profiles, '选择要删除的配置')
    preview(next(p for p in profiles if p['name'] == selected), target)
    print('只删除保存项，当前 Claude 配置保留。')
    if choose('确认删除以上保存的配置？', [('n', '取消'), ('y', '确认删除')]) != 'y':
        raise Cancelled()
    return selected


def connection(existing=None):
    require_terminal()
    if existing is not None:
        preview(existing)
    settings = dict(existing or {})
    settings['env'] = dict(settings.get('env', {}))
    endpoint = ask('Base URL (blank keeps current; cancel): ').strip()
    if endpoint:
        settings['env']['ANTHROPIC_BASE_URL'] = endpoint
    choices = [('api_key', 'API Key'), ('bearer_token', 'Bearer Token')]
    if existing is not None:
        choices.insert(0, ('', '保持当前认证'))
    kind = choose('选择认证方式', choices)
    if kind:
        key = 'ANTHROPIC_API_KEY' if kind == 'api_key' else 'ANTHROPIC_AUTH_TOKEN'
        settings['env'][key] = ask('Secret (cancel): ', secret=True)
    return extract_settings(settings, auth=kind or None)


SLOT_LABELS = {'opus': 'Opus', 'sonnet': 'Sonnet', 'haiku': 'Haiku', 'fable': 'Fable',
               'startup': '默认启动', 'subagent': '子代理默认'}


def choose_model(settings, slot, cache):
    env = settings.get('env', {})
    current = env.get(SLOTS.get(slot, ''), '')
    if slot == 'startup' and not current:
        current = settings.get('model', '')
    candidates = []
    aliases = ('opus', 'sonnet', 'haiku', 'fable')
    if slot in ('startup', 'subagent'):
        for alias in aliases:
            candidates.append((alias, '跟随 ' + SLOT_LABELS[alias] + ' 槽位'))
    for model in [current, *(env.get(key, '') for key in MODEL_BINDINGS),
                  settings.get('model', ''),
                  *(row['model'] for row in settings.get('modelPicker', {}).get('options', []))]:
        if model and model not in aliases and all(key != model for key, _ in candidates):
            candidates.append((model, model + ('  [当前]' if model == current else '')))
    catalog_key, custom_key = object(), object()
    candidates.extend([(catalog_key, '更多模型：CloudCLI 目录…'), (custom_key, '手动输入模型 ID…')])
    while True:
        selected = choose('选择 ' + SLOT_LABELS.get(slot, '自定义') + ' 模型', candidates,
                          default=current, allow_custom=True)
        try:
            if selected is custom_key:
                model = ask('模型 ID（Esc 返回）: ').strip()
                if not model:
                    print('模型 ID 不能为空。')
                    continue
                return model
            if selected is catalog_key:
                import ccswitch_backend as backend
                if 'catalog' not in cache:
                    cache['catalog'] = backend.load_model_catalog(settings=settings)
                models, live = cache['catalog']
                source = 'CloudCLI 账号目录' if live else 'CloudCLI 本地模型清单'
                compatible = [backend.catalog_model_choice(m)
                              for m in models if 'anthropic' in m.get('protocols', [])]
                if not compatible:
                    print('目录没有支持 Claude 的模型。')
                    continue
                date = '' if live else ' · ' + backend.STATIC_CATALOG_UPDATED_AT
                return choose(source + ' · ' + str(len(compatible)) + ' 个' + date, compatible)
            return selected
        except Back:
            continue


def _menu_editor(draft, cache):
    action = choose('额外模型菜单', [('add', '添加模型'), ('rename', '修改显示名称'),
                    ('remove', '删除模型'), ('move', '调整顺序'),
                    ('builtins', '设置内置菜单'), ('unify', '统一所有模型（含自定义菜单）')])
    if action == 'unify':
        return unify_slots(draft, choose_model(draft, 'unify', cache))
    return _edit_menu_action(draft, action, cache)


def _edit_menu_action(draft, action, cache):
    if action == 'add':
        model = choose_model(draft, 'menu', cache)
        label = ask('显示名称（可留空）: ').strip()
        description = ask('说明（可留空）: ').strip()
        behaves_as = choose('行为参考', [('', '不指定'), ('opus', 'Opus'),
                                         ('sonnet', 'Sonnet'), ('haiku', 'Haiku')])
        return edit_menu(draft, 'add', model=model, label=label or None,
                         description=description or None, behaves_as=behaves_as or None)
    if action == 'builtins':
        replace = choose('Claude 内置菜单', [('keep', '保留内置项，追加自定义模型'),
                                             ('replace', '只显示自定义模型')])
        return edit_menu(draft, 'builtins', replace_built_in=replace == 'replace')
    rows = draft.get('modelPicker', {}).get('options', [])
    if not rows:
        print('还没有自定义菜单项，请先添加。')
        return draft
    labels = [(str(i), row.get('label') or row['model']) for i, row in enumerate(rows)]
    index = int(choose('选择要修改的菜单项', labels))
    extra = {}
    if action == 'rename':
        extra['label'] = ask('新的显示名称: ')
    elif action == 'move':
        extra['to'] = int(choose('移动到哪个位置', labels, default=str(index)))
    return edit_menu(draft, action, index=index, **extra)


def slot_wizard(settings, target, *, name=None):
    require_terminal()
    draft, cache, selected = extract_settings(settings), {}, None
    while True:
        preview({'name': name, 'settings': draft}, target, compact=True)
        env = draft.get('env', {})
        choices = [(slot, SLOT_LABELS[slot] + '：' +
                    (env.get(key) or (draft.get('model') if slot == 'startup' else '') or '未设置'))
                   for slot, key in SLOTS.items()]
        choices.extend([('menu', '更多设置：额外模型菜单、统一模型'),
                        ('apply', '保存并应用'), ('save', '只保存'), ('cancel', '取消修改')])
        action = choose('编辑槽位', choices, default=selected, allow_custom=True)
        try:
            if action in SLOTS:
                draft = set_slot(draft, action, choose_model(draft, action, cache))
            elif action == 'menu':
                draft = _menu_editor(draft, cache)
            elif action == 'unify':
                draft = unify_slots(draft, choose_model(draft, 'unify', cache))
            elif action.startswith('menu-'):
                draft = _edit_menu_action(draft, action[5:], cache)
            elif action in ('save', 'apply'):
                return draft, action == 'apply'
            elif action == 'cancel':
                raise Cancelled()
            elif action == 'preview':
                continue
            else:
                print('请选择菜单中的一项。')
                continue
            selected = 'apply'
        except Back:
            selected = action
        except ValueError:
            print('槽位或菜单值无效，草稿未修改。')
