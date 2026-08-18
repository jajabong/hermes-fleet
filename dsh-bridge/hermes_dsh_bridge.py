"""Hermes-DSH Bridge: Hermes Strategic Layer -> DSH Tactical Runtime.

Invoked by Hermes dispatcher (engine=dsh) or directly:
    python3 hermes_dsh_bridge.py "task" [--preset P] [--provider X] [--model Y] [--out FILE]

Provider routing honors explicit --provider/--model; otherwise falls back to
keyword inference in PROVIDER_MAP. Defaults to deepseek-official/deepseek-v4-flash.
"""

import argparse
import os
import sys
from pathlib import Path

import yaml
from deepseek_harness import DeepSeekHarness

# Provider keys live in $DSH_HOME/settings.yaml (llm-pi-ai.providers.*). The
# bundled SDK runtime resolves DEEPSEEK_API_KEY from the launching environment,
# so we load the key for the selected provider and inject it into env before
# constructing the harness. No secret is hardcoded or logged here.
DSH_HOME = Path(os.environ.get('DSH_HOME') or Path.home() / '.dsh')
DSH_SETTINGS = DSH_HOME / 'settings.yaml'


def load_api_key(provider: str) -> str | None:
    """Return the apiKey for a provider from settings.yaml, or None."""
    try:
        data = yaml.safe_load(DSH_SETTINGS.read_text(encoding='utf-8')) or {}
    except Exception:
        return None
    provider_cfg = ((data.get('llm-pi-ai') or {}).get('providers') or {}).get(provider)
    if not isinstance(provider_cfg, dict):
        return None
    key = provider_cfg.get('apiKey')
    return str(key) if isinstance(key, str) and key else None


def inject_api_key(provider: str) -> None:
    """Set the provider's API key env var if present in settings.yaml.

    deepseek-official -> DEEPSEEK_API_KEY; anything else -> <PROVIDER>_API_KEY.
    """
    key = load_api_key(provider)
    if not key:
        return
    if provider == 'deepseek-official':
        os.environ['DEEPSEEK_API_KEY'] = key
    else:
        os.environ[f'{provider.upper().replace("-", "_")}_API_KEY'] = key

# keyword -> DSH preset (priority order matters: first match wins)
# Use word-boundary-ish matching to avoid path-name false positives like
# `/tmp/plan-test` matching `test` -> `code`.
_TASK_PRESET_RULES = [
    ('excel',       ('excel',)),
    ('spreadsheet', ('excel',)),
    ('xlsx',        ('excel',)),
    ('chart',       ('excel',)),
    ('browser',     ('browser',)),
    ('screenshot',  ('browser',)),
    ('web',         ('browser',)),
    ('research',    ('research',)),
    ('search',      ('research',)),
    ('summarize',   ('research',)),
    ('analyze',     ('research',)),
    ('implement',   ('code',)),
    ('refactor',    ('code',)),
    ('debug',       ('code',)),
    ('review',      ('code',)),
    ('write',       ('writing',)),
    ('draft',       ('writing',)),
    ('translate',   ('writing',)),
    ('ppt',         ('writing',)),
    ('presentation',('writing',)),
    ('slides',      ('writing',)),
    ('code',        ('code',)),
    ('test',        ('code',)),
]


def _match_preset(task: str) -> str:
    """Pick preset by keyword, preferring longer/more-specific tokens."""
    lower = task.lower()
    for keyword, (preset,) in _TASK_PRESET_RULES:
        if keyword in lower:
            return preset
    return 'default'

# preset -> (provider, model)
PROVIDER_MAP = {
    'code':     ('deepseek-official', 'deepseek-v4-flash'),
    'research': ('deepseek-official', 'deepseek-v4-flash'),
    'excel':    ('deepseek-official', 'deepseek-v4-flash'),
    'browser':  ('deepseek-official', 'deepseek-v4-flash'),
    'writing':  ('deepseek-official', 'deepseek-v4-flash'),
    'default':  ('deepseek-official', 'deepseek-v4-flash'),
}


class HermesStrategicLayer:
    def __init__(self, preset=None, provider=None, model=None):
        self.override_preset = preset
        self.override_provider = provider
        self.override_model = model

    def analyze_task(self, task: str) -> dict:
        preset = self.override_preset
        if not preset:
            preset = _match_preset(task)

        provider, model = (
            (self.override_provider, self.override_model)
            if self.override_provider and self.override_model
            else PROVIDER_MAP.get(preset, PROVIDER_MAP['default'])
        )

        if self.override_provider and not self.override_model:
            model = PROVIDER_MAP.get(preset, PROVIDER_MAP['default'])[1]
        if self.override_model and not self.override_provider:
            provider = PROVIDER_MAP.get(preset, PROVIDER_MAP['default'])[0]

        return {'preset': preset, 'provider': provider, 'model': model}

    def execute(self, task: str) -> str:
        plan = self.analyze_task(task)
        inject_api_key(plan['provider'])
        print(f'[Hermes] preset={plan["preset"]} provider={plan["provider"]} model={plan["model"]}',
              file=sys.stderr)
        with DeepSeekHarness(
            provider=plan['provider'],
            model=plan['model'],
            max_tokens=49152,
        ) as harness:
            result = harness.run(task)
        return result.final_response or ''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('task', nargs='*', default=None)
    parser.add_argument('--preset', default=None)
    parser.add_argument('--provider', default=None)
    parser.add_argument('--model', default=None)
    parser.add_argument('--out', default=None)
    args = parser.parse_args()

    task = ' '.join(args.task) if args.task else 'Hello, what can you do?'
    layer = HermesStrategicLayer(
        preset=args.preset,
        provider=args.provider,
        model=args.model,
    )
    response = layer.execute(task)

    if args.out:
        os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(response)
        print(f'[Hermes] written -> {args.out}', file=sys.stderr)

    print(response)
    return 0


if __name__ == '__main__':
    sys.exit(main())