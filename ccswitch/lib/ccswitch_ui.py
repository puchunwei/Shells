"""Terminal-only input and the slot draft wizard. No persistence or application."""
import getpass
import sys
from urllib.parse import urlsplit
from ccswitch_profiles import extract_settings, redact
from ccswitch_slots import SLOTS, edit_menu, set_slot, unify_slots


class Cancelled(Exception):
    pass


def require_terminal():
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ValueError('Interactive input requires stdin and stdout terminals; specify a name and --from file')


def ask(prompt, *, secret=False):
    require_terminal()
    try:
        value = getpass.getpass(prompt) if secret else input(prompt)
    except (EOFError, KeyboardInterrupt):
        raise Cancelled() from None
    if value.strip().lower() in ('cancel', 'quit'):
        raise Cancelled()
    return value


def preview(value, target=None):
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
    print('Models: ' + (models or '(not configured)'))
    print('Menu: ' + str(len(settings.get('modelPicker', {}).get('options', []))) + ' custom entries')
    if target is not None:
        print('Global target: ' + str(target))


def select_profile(profiles, target):
    require_terminal()
    if not profiles:
        raise ValueError('No saved profiles; add or import a profile first')
    names = [profile['name'] for profile in profiles]
    for index, name in enumerate(names, 1):
        print(str(index) + '. ' + name)
    selected = ask('Profile (name or number; cancel): ').strip()
    if selected.isdigit() and 1 <= int(selected) <= len(names):
        selected = names[int(selected) - 1]
    if selected not in names:
        raise ValueError('Select a saved profile')
    preview(next(profile for profile in profiles if profile['name'] == selected), target)
    if ask('Apply to this global target? [y/N]: ').strip().lower() != 'y':
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
    kind = ask('Authentication [api_key/bearer_token] (blank keeps current): ').strip()
    if kind:
        if kind not in ('api_key', 'bearer_token'):
            raise ValueError('Authentication must be api_key or bearer_token')
        key = 'ANTHROPIC_API_KEY' if kind == 'api_key' else 'ANTHROPIC_AUTH_TOKEN'
        settings['env'][key] = ask('Secret (cancel): ', secret=True)
    return extract_settings(settings, auth=kind or None)


def slot_wizard(settings, target):
    require_terminal()
    draft = extract_settings(settings)
    while True:
        preview(draft, target)
        print('Actions: opus, sonnet, haiku, startup, subagent, unify, menu-add, menu-rename,')
        print('menu-move, menu-remove, menu-builtins, preview, save, apply (save and apply), cancel')
        action = ask('Action: ').strip().lower()
        try:
            if action in SLOTS:
                draft = set_slot(draft, action, ask('Model (startup accepts alias or fixed ID): ').strip())
            elif action == 'unify':
                draft = unify_slots(draft, ask('Model for all slots: ').strip())
            elif action == 'menu-add':
                model = ask('Model: ').strip()
                label = ask('Label (optional): ').strip()
                description = ask('Description (optional): ').strip()
                behaves_as = ask('Behaves as (optional): ').strip()
                draft = edit_menu(draft, 'add', model=model, label=label or None,
                                  description=description or None, behaves_as=behaves_as or None)
            elif action in ('menu-rename', 'menu-remove', 'menu-move'):
                index = int(ask('Index (starts at 0): '))
                extra = {}
                if action == 'menu-rename':
                    extra['label'] = ask('New label: ')
                if action == 'menu-move':
                    extra['to'] = int(ask('Destination index: '))
                draft = edit_menu(draft, action[len('menu-'):], index=index, **extra)
            elif action == 'menu-builtins':
                replace = ask('Replace built-in options? [y/N]: ').strip().lower() == 'y'
                draft = edit_menu(draft, 'builtins', replace_built_in=replace)
            elif action in ('save', 'apply'):
                return draft, action == 'apply'
            elif action == 'preview':
                continue
            else:
                print('Choose an action from the list.')
        except ValueError:
            print('Invalid slot/menu value; draft was not changed.')
