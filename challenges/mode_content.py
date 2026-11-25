"""Validation and access helpers for mode-gated challenge content.

``mode_content`` is optional, additive JSON stored on ``Challenge``. It is used
only by authenticated, mode-aware endpoints and is never returned through the
ordinary public challenge serializers.

The schema is intentionally small and explicit:

* ``student`` - guided learning content
* ``competitor`` - independent challenge content
* ``solution`` - post-solve learning content

Unknown keys are rejected. Plaintext challenge flags, flag-like values and
credential-like secrets must not be stored here.
"""

from __future__ import annotations

import re

from django.utils.translation import gettext_lazy as _

from rest_framework import serializers

from submissions.models import Solve

from .models import Challenge

MODE_STUDENT = 'student'
MODE_COMPETITOR = 'competitor'
VALID_MODES = {MODE_STUDENT, MODE_COMPETITOR}

MAX_TOTAL_JSON_CHARS = 20000
MAX_LIST_ITEMS = 30
MAX_SHORT_STRING = 280
MAX_TEXT_STRING = 4000
MAX_LONG_STRING = 8000

# Never allow plaintext flag values or flag-like tokens in mode content.
_FLAG_LIKE_RE = re.compile(r'\b(?:CTF|FLAG)\{[^}\r\n]{0,256}\}', re.IGNORECASE)
# Conservative guard against credential-like material.
_SECRET_LIKE_RE = re.compile(
    r'(?i)\b(password|passwd|pwd|secret|token|api[_ -]?key|private[_ -]?key)\b\s*[:=]'
)

_TOP_LEVEL_KEYS = {'student', 'competitor', 'solution'}

_STUDENT_KEYS = {
    'introduction',
    'scenario',
    'learning_objectives',
    'tasks',
    'checkpoints',
    'guidance',
    'review_questions',
    'common_mistakes',
    'remediation_guidance',
}

_COMPETITOR_KEYS = {
    'challenge_rules',
    'objective',
    'time_limit',
    'submission_instructions',
}

_SOLUTION_KEYS = {
    'explanation',
    'walkthrough',
    'expected_result',
    'learning_takeaways',
}


def is_mode_aware(challenge: Challenge) -> bool:
    """Return True when a challenge carries configured mode-gated content."""
    content = getattr(challenge, 'mode_content', None)
    return isinstance(content, dict) and bool(content)


def resolve_learning_mode(user) -> str:
    """Resolve the effective learning mode from persisted user data only.

    Query params, headers and request bodies must never influence this value.
    Invalid/missing persisted values fall back to the least-disclosure mode.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return MODE_COMPETITOR
    mode = getattr(user, 'effective_learning_mode', None)
    if mode in VALID_MODES:
        return mode
    normalizer = getattr(user, 'normalize_learning_mode', None)
    if callable(normalizer):
        normalized = normalizer(getattr(user, 'learning_mode', None))
        if normalized in VALID_MODES:
            return normalized
    return MODE_COMPETITOR


def user_has_solved(user, challenge: Challenge) -> bool:
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    return Solve.objects.filter(user=user, challenge=challenge).exists()


def get_mode_visible_content(challenge: Challenge, user):
    """Return the caller-allowed mode content (never cross-mode, never solution)."""
    content = challenge.mode_content if isinstance(challenge.mode_content, dict) else {}
    mode = resolve_learning_mode(user)
    section = content.get(mode)
    if not isinstance(section, dict):
        section = {}
    return {
        'mode': mode,
        'challenge_id': challenge.pk,
        'content': section,
        'solution_available': False,
    }


def get_solution_content(challenge: Challenge, user):
    """Return solution content only after a DB-backed solve check.

    Policy: solutions are available only to student-mode users who have a
    Solve record for this exact challenge. Competitor users do not receive
    solution content through this endpoint.
    """
    mode = resolve_learning_mode(user)
    solved = user_has_solved(user, challenge)
    content = challenge.mode_content if isinstance(challenge.mode_content, dict) else {}
    solution = content.get('solution')
    allowed = mode == MODE_STUDENT and solved and isinstance(solution, dict)

    return {
        'challenge_id': challenge.pk,
        'mode': mode,
        'solved': solved,
        'solution_available': allowed,
        'solution': solution if allowed else None,
    }


def validate_mode_content(value):
    """Validate and normalize ``mode_content`` for Challenge writes.

    Empty values are normalized to ``{}`` for backwards compatibility.
    """
    if value in (None, '', {}):
        return {}

    if not isinstance(value, dict):
        raise serializers.ValidationError('mode_content must be an object.')

    _reject_forbidden_text(_json_size_probe(value), 'mode_content')

    unknown_top = sorted(set(value.keys()) - _TOP_LEVEL_KEYS)
    if unknown_top:
        raise serializers.ValidationError(
            {'mode_content': f'Unknown top-level keys: {", ".join(unknown_top)}.'}
        )

    normalized = {}

    if 'student' in value:
        normalized['student'] = _validate_section(
            value['student'], _STUDENT_KEYS, 'student'
        )
    if 'competitor' in value:
        normalized['competitor'] = _validate_section(
            value['competitor'], _COMPETITOR_KEYS, 'competitor'
        )
    if 'solution' in value:
        normalized['solution'] = _validate_section(
            value['solution'], _SOLUTION_KEYS, 'solution'
        )

    # If provided, sections must be objects (possibly empty) and the overall
    # structure must remain within size limits after normalization.
    _ensure_total_size(normalized)
    _reject_forbidden_text(_json_size_probe(normalized), 'mode_content')

    # Do not persist empty named sections as noise, but keep explicit empty
    # top-level object semantics as {}.
    cleaned = {k: v for k, v in normalized.items() if v}
    return cleaned


def _json_size_probe(value):
    try:
        import json

        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    except Exception:
        return str(value)


def _ensure_total_size(value):
    rendered = _json_size_probe(value)
    if len(rendered) > MAX_TOTAL_JSON_CHARS:
        raise serializers.ValidationError(
            {
                'mode_content': (
                    f'mode_content is too large (max {MAX_TOTAL_JSON_CHARS} characters '
                    'when serialized).'
                )
            }
        )


def _reject_forbidden_text(text, field_name):
    if not isinstance(text, str):
        return
    if _FLAG_LIKE_RE.search(text):
        raise serializers.ValidationError(
            {field_name: 'mode_content must not contain plaintext flags or flag-like values.'}
        )
    if _SECRET_LIKE_RE.search(text):
        raise serializers.ValidationError(
            {field_name: 'mode_content must not contain credentials or secrets.'}
        )


def _validate_section(value, allowed_keys, section_name):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise serializers.ValidationError(
            {f'mode_content.{section_name}': 'Must be an object.'}
        )

    unknown = sorted(set(value.keys()) - allowed_keys)
    if unknown:
        raise serializers.ValidationError(
            {
                f'mode_content.{section_name}': (
                    f'Unknown keys: {", ".join(unknown)}.'
                )
            }
        )

    normalized = {}

    if section_name == 'student':
        normalized.update(_validate_student_section(value))
    elif section_name == 'competitor':
        normalized.update(_validate_competitor_section(value))
    elif section_name == 'solution':
        normalized.update(_validate_solution_section(value))

    return {k: v for k, v in normalized.items() if v not in (None, '', [], {})}


def _validate_student_section(value):
    data = {}
    if 'introduction' in value:
        data['introduction'] = _validate_text(value['introduction'], 'mode_content.student.introduction', MAX_TEXT_STRING)
    if 'scenario' in value:
        data['scenario'] = _validate_text(value['scenario'], 'mode_content.student.scenario', MAX_TEXT_STRING)
    if 'learning_objectives' in value:
        data['learning_objectives'] = _validate_string_list(
            value['learning_objectives'], 'mode_content.student.learning_objectives', MAX_SHORT_STRING
        )
    if 'tasks' in value:
        data['tasks'] = _validate_structured_items(
            value['tasks'], 'mode_content.student.tasks',
            allowed_keys={'id', 'title', 'description', 'step', 'order'},
            text_keys={'id', 'title', 'description', 'step'},
            max_text=MAX_TEXT_STRING,
        )
    if 'checkpoints' in value:
        data['checkpoints'] = _validate_structured_items(
            value['checkpoints'], 'mode_content.student.checkpoints',
            allowed_keys={'id', 'title', 'description', 'criteria', 'order'},
            text_keys={'id', 'title', 'description', 'criteria'},
            max_text=MAX_TEXT_STRING,
        )
    if 'guidance' in value:
        data['guidance'] = _validate_structured_items(
            value['guidance'], 'mode_content.student.guidance',
            allowed_keys={'id', 'title', 'explanation', 'text', 'order'},
            text_keys={'id', 'title', 'explanation', 'text'},
            max_text=MAX_TEXT_STRING,
        )
    if 'review_questions' in value:
        data['review_questions'] = _validate_structured_items(
            value['review_questions'], 'mode_content.student.review_questions',
            allowed_keys={'id', 'question', 'answer', 'explanation', 'order'},
            text_keys={'id', 'question', 'answer', 'explanation'},
            max_text=MAX_TEXT_STRING,
        )
    if 'common_mistakes' in value:
        data['common_mistakes'] = _validate_structured_items(
            value['common_mistakes'], 'mode_content.student.common_mistakes',
            allowed_keys={'id', 'mistake', 'description', 'example', 'order'},
            text_keys={'id', 'mistake', 'description', 'example'},
            max_text=MAX_TEXT_STRING,
        )
    if 'remediation_guidance' in value:
        data['remediation_guidance'] = _validate_structured_items(
            value['remediation_guidance'], 'mode_content.student.remediation_guidance',
            allowed_keys={'id', 'title', 'guidance', 'remediation', 'text', 'order'},
            text_keys={'id', 'title', 'guidance', 'remediation', 'text'},
            max_text=MAX_TEXT_STRING,
        )
    return data


def _validate_competitor_section(value):
    data = {}
    if 'challenge_rules' in value:
        data['challenge_rules'] = _validate_string_list(
            value['challenge_rules'], 'mode_content.competitor.challenge_rules', MAX_TEXT_STRING
        )
    if 'objective' in value:
        data['objective'] = _validate_text(value['objective'], 'mode_content.competitor.objective', MAX_TEXT_STRING)
    if 'time_limit' in value:
        data['time_limit'] = _validate_time_limit(value['time_limit'], 'mode_content.competitor.time_limit')
    if 'submission_instructions' in value:
        data['submission_instructions'] = _validate_text(
            value['submission_instructions'], 'mode_content.competitor.submission_instructions', MAX_TEXT_STRING
        )
    return data


def _validate_solution_section(value):
    data = {}
    if 'explanation' in value:
        data['explanation'] = _validate_text(value['explanation'], 'mode_content.solution.explanation', MAX_LONG_STRING)
    if 'walkthrough' in value:
        data['walkthrough'] = _validate_walkthrough(value['walkthrough'], 'mode_content.solution.walkthrough')
    if 'expected_result' in value:
        data['expected_result'] = _validate_text(value['expected_result'], 'mode_content.solution.expected_result', MAX_TEXT_STRING)
    if 'learning_takeaways' in value:
        data['learning_takeaways'] = _validate_string_list(
            value['learning_takeaways'], 'mode_content.solution.learning_takeaways', MAX_SHORT_STRING
        )
    return data


def _validate_text(value, field_name, max_length):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise serializers.ValidationError({field_name: 'Must be a string.'})
    text = value.strip()
    if len(text) > max_length:
        raise serializers.ValidationError({field_name: f'Must be at most {max_length} characters.'})
    _reject_forbidden_text(text, field_name)
    return text


def _validate_string_list(value, field_name, max_item_length):
    if value is None:
        return []
    if not isinstance(value, list):
        raise serializers.ValidationError({field_name: 'Must be a list.'})
    if len(value) > MAX_LIST_ITEMS:
        raise serializers.ValidationError({field_name: f'Must contain at most {MAX_LIST_ITEMS} items.'})
    items = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise serializers.ValidationError({field_name: f'Item {index} must be a string.'})
        text = item.strip()
        if len(text) > max_item_length:
            raise serializers.ValidationError(
                {field_name: f'Item {index} must be at most {max_item_length} characters.'}
            )
        _reject_forbidden_text(text, field_name)
        if text:
            items.append(text)
    return items


def _validate_time_limit(value, field_name):
    """Accept a structured time limit or a short descriptive string."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if len(text) > MAX_SHORT_STRING:
            raise serializers.ValidationError({field_name: f'Must be at most {MAX_SHORT_STRING} characters.'})
        _reject_forbidden_text(text, field_name)
        return text
    if isinstance(value, dict):
        allowed = {'minutes', 'seconds', 'label'}
        unknown = sorted(set(value.keys()) - allowed)
        if unknown:
            raise serializers.ValidationError({field_name: f'Unknown keys: {", ".join(unknown)}.'})
        normalized = {}
        for key in ('minutes', 'seconds'):
            if key in value:
                number = value[key]
                if isinstance(number, bool) or not isinstance(number, int):
                    raise serializers.ValidationError({field_name: f'{key} must be an integer.'})
                if number < 0 or number > 24 * 60 * 60:
                    raise serializers.ValidationError({field_name: f'{key} is out of range.'})
                normalized[key] = number
        if 'label' in value:
            normalized['label'] = _validate_text(value['label'], f'{field_name}.label', MAX_SHORT_STRING)
        if not normalized:
            raise serializers.ValidationError({field_name: 'Must include minutes, seconds, or label.'})
        return normalized
    raise serializers.ValidationError({field_name: 'Must be a string or an object.'})


def _validate_structured_items(value, field_name, allowed_keys, text_keys, max_text):
    if value is None:
        return []
    if not isinstance(value, list):
        raise serializers.ValidationError({field_name: 'Must be a list.'})
    if len(value) > MAX_LIST_ITEMS:
        raise serializers.ValidationError({field_name: f'Must contain at most {MAX_LIST_ITEMS} items.'})

    items = []
    for index, item in enumerate(value):
        path = f'{field_name}[{index}]'
        if isinstance(item, str):
            text = _validate_text(item, path, max_text)
            if text:
                items.append({'description': text})
            continue
        if not isinstance(item, dict):
            raise serializers.ValidationError({path: 'Must be an object or a string.'})
        unknown = sorted(set(item.keys()) - allowed_keys)
        if unknown:
            raise serializers.ValidationError({path: f'Unknown keys: {", ".join(unknown)}.'})
        normalized = {}
        for key, val in item.items():
            if key == 'order':
                if isinstance(val, bool) or not isinstance(val, int):
                    raise serializers.ValidationError({f'{path}.order': 'Must be an integer.'})
                if val < 0 or val > 10000:
                    raise serializers.ValidationError({f'{path}.order': 'Out of range.'})
                normalized['order'] = val
                continue
            if key in text_keys:
                text = _validate_text(val, f'{path}.{key}', max_text)
                if text:
                    normalized[key] = text
                continue
            raise serializers.ValidationError({f'{path}.{key}': 'Unsupported field.'})
        if normalized:
            items.append(normalized)
    return items


def _validate_walkthrough(value, field_name):
    """Walkthrough may be a text block or a list of step strings/objects."""
    if value is None:
        return ''
    if isinstance(value, str):
        return _validate_text(value, field_name, MAX_LONG_STRING)
    if isinstance(value, list):
        return _validate_structured_items(
            value,
            field_name,
            allowed_keys={'id', 'title', 'description', 'step', 'text', 'order'},
            text_keys={'id', 'title', 'description', 'step', 'text'},
            max_text=MAX_LONG_STRING,
        )
    raise serializers.ValidationError({field_name: 'Must be a string or a list.'})
