"""Hermes-DSH Bridge: Hermes Strategic Layer -> DSH Tactical Runtime.

Invoked by Hermes dispatcher (engine=dsh) or directly:
    python3 hermes_dsh_bridge.py "task" [--preset P] [--provider X] [--model Y] [--out FILE]

Provider routing honors explicit --provider/--model; otherwise falls back to
keyword inference in PROVIDER_MAP. Defaults to deepseek-official/deepseek-v4-flash.
"""

import argparse
import os
import sys
from deepseek_harness import DeepSeekHarness

# Ensure API keys exist for the DSH subprocess before importing/invoking the SDK.
# Real keys are loaded from $DSH_HOME/.credentials.yaml by the DSH runtime;
# these setdefault calls are only a fallback for local runs and contain NO secrets.
os.environ.setdefault('DEEPSEEK_API_KEY', '<set via $DSH_HOME/.credentials.yaml>')
os.environ.setdefault('MINIMAX_API_KEY',   '<set via $DSH_HOME/.credentials.yaml>')

# keyword -> DSH preset
TASK_PRESET_MAP = {
    'code':        'code',
    'refactor':    'code',
    'debug':       'code',
    'test':        'code',
    'implement':   'code',
    'review':      'code',
    'research':    'research',
    'search':      'research',
    'analyze':     'research',
    'summarize':   'research',
    'excel':       'excel',
    'spreadsheet': 'excel',
    'report':      'excel',
    'chart':       'excel',
    'browser':     'browser',
    'web':         'browser',
    'screenshot':  'browser',
    'write':       'writing',
    'draft':       'writing',
    'translate':   'writing',
}

# preset -> (provider, model)
PROVIDER_MAP = {
    'code':     ('deepseek-official', 'deepseek-v4-flash'),
    'research': ('deepseek-official', 'deepseek-v4-flash'),
    'excel':    ('minimax',           'MiniMax-M3'),
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
            task_lower = task.lower()
            preset = 'default'
            for key, val in TASK_PRESET_MAP.items():
                if key in task_lower:
                    preset = val
                    break

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