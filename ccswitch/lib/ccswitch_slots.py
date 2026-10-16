"""Shared, private draft transformations for both the slot wizard and CLI."""
import copy
from ccswitch_profiles import extract_settings

SLOTS = {
    'opus': 'ANTHROPIC_DEFAULT_OPUS_MODEL',
    'sonnet': 'ANTHROPIC_DEFAULT_SONNET_MODEL',
    'haiku': 'ANTHROPIC_DEFAULT_HAIKU_MODEL',
    'startup': 'ANTHROPIC_MODEL',
    'subagent': 'CLAUDE_CODE_SUBAGENT_MODEL',
}
# FORCE is a policy flag; assigning a model ID to it would change its meaning.
MODEL_BINDINGS = tuple(SLOTS.values()) + (
    'ANTHROPIC_SMALL_FAST_MODEL', 'ANTHROPIC_DEFAULT_MODEL',
    'ANTHROPIC_DEFAULT_FABLE_MODEL', 'ANTHROPIC_CUSTOM_MODEL_OPTION',
)


def set_slot(settings, slot, model):
    draft = copy.deepcopy(settings)
    if slot not in SLOTS:
        raise ValueError('Unknown model slot')
    if not model:
        raise ValueError('Model is required')
    draft.setdefault('env', {})[SLOTS[slot]] = model
    if slot == 'startup':
        draft['model'] = model
    return extract_settings(draft)


def unify_slots(settings, model):
    draft = set_slot(settings, 'startup', model)
    for key in MODEL_BINDINGS:
        draft['env'][key] = model
    draft['env']['ANTHROPIC_CUSTOM_MODEL_OPTION_NAME'] = model
    draft['env']['ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION'] = 'Selected model'
    for option in draft.get('modelPicker', {}).get('options', []):
        option['model'] = model
    return extract_settings(draft)


def edit_menu(settings, action, *, model=None, label=None, description=None,
              behaves_as=None, index=None, to=None, replace_built_in=None):
    draft = copy.deepcopy(settings)
    picker = draft.setdefault('modelPicker', {})
    picker.setdefault('replaceBuiltInOptions', False)
    options = picker.setdefault('options', [])
    if action == 'add':
        row = {'model': model}
        for key, value in (('label', label), ('description', description), ('behavesAs', behaves_as)):
            if value is not None:
                row[key] = value
        options.append(row)
    elif action in ('remove', 'move', 'rename'):
        if not isinstance(index, int) or not 0 <= index < len(options):
            raise ValueError('Menu index is out of range (indexes start at 0)')
        if action == 'remove':
            options.pop(index)
        elif action == 'move':
            if not isinstance(to, int) or not 0 <= to < len(options):
                raise ValueError('Menu destination is out of range (indexes start at 0)')
            options.insert(to, options.pop(index))
        else:
            options[index]['label'] = label
    elif action == 'builtins':
        if not isinstance(replace_built_in, bool):
            raise ValueError('replaceBuiltInOptions must be a boolean')
        picker['replaceBuiltInOptions'] = replace_built_in
    else:
        raise ValueError('Unknown menu action')
    return extract_settings(draft)
