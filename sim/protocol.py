"""Recorded official config and a small draft-07 subset validator for this kit schema."""
from __future__ import annotations
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KIT = ROOT / 'kit'
SCHEMA = json.loads((KIT / 'mechfight.schema.json').read_text())
with gzip.open(KIT / 'check/stream.jsonl.gz', 'rt') as stream:
    CONFIG = json.loads(next(stream))['config']


def validate(kind: str, value):
    """Validate the schema features used by the bundled draft-07 contract."""
    def check(rule, obj, path):
        if '$ref' in rule:
            return check(SCHEMA['definitions'][rule['$ref'].split('/')[-1]], obj, path)
        options = rule.get('oneOf', rule.get('anyOf'))
        if options is not None:
            passed = 0
            for option in options:
                try:
                    check(option, obj, path)
                    passed += 1
                except ValueError:
                    pass
            if (passed != 1 if 'oneOf' in rule else passed == 0):
                raise ValueError(f'{path}: no unique valid alternative')
            return
        typ = rule.get('type')
        valid = {'object': lambda x: isinstance(x, dict), 'array': lambda x: isinstance(x, list),
                 'string': lambda x: isinstance(x, str), 'number': lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
                 'boolean': lambda x: isinstance(x, bool), 'null': lambda x: x is None}
        if typ and not any(valid[t](obj) for t in (typ if isinstance(typ,list) else [typ])):
            raise ValueError(f'{path}: expected {typ}')
        if 'const' in rule and obj != rule['const']:
            raise ValueError(f'{path}: wrong constant')
        if 'enum' in rule and obj not in rule['enum']:
            raise ValueError(f'{path}: invalid enum')
        if typ == 'object':
            for key in rule.get('required', []):
                if key not in obj:
                    raise ValueError(f'{path}.{key}: required')
            if rule.get('additionalProperties', True) is False:
                extra = obj.keys() - rule.get('properties', {}).keys()
                if extra:
                    raise ValueError(f'{path}: extra keys {extra}')
            for key, val in obj.items():
                sub = rule.get('properties', {}).get(key, rule.get('additionalProperties'))
                if isinstance(sub, dict):
                    check(sub, val, f'{path}.{key}')
        if typ == 'array':
            if not rule.get('minItems', 0) <= len(obj) <= rule.get('maxItems', float('inf')):
                raise ValueError(f'{path}: array length')
            for i, item in enumerate(obj):
                check(rule.get('items', {}), item, f'{path}[{i}]')
    check(SCHEMA['definitions'][kind], value, kind)
    return value
