"""Build guidance and exact-scope checks; not broad live planning qualification."""
from copy import deepcopy
import json

import pytest

from ai_inspector.facility_layout.generation_agent import CONTEXT_TOOL, PREVIEW_TOOL, REQUIREMENTS_TOOL, generation_tool_specs
from ai_inspector.facility_layout.generation_build_method import build_method_summary, build_method_stages
from ai_inspector.facility_layout.generation_requirements import GenerationRequirementError, build_generation_ledger, evaluate_generation_requirements
from tests.test_facility_generation_requirements import body
from tests.test_facility_generation_admission import case, assert_code
from tests.test_facility_generation_agent import chat, execute


def scope_body(kind, parameters):
    value = body()
    entry = deepcopy(value['requirements'][0])
    entry['requirementId'] = 'scope'
    entry['predicate'] = {'kind': kind, 'subjectId': value['layoutId'], 'parameters': parameters}
    value['requirements'].append(entry)
    return value


def scope_passes(kind, parameters, package):
    result = evaluate_generation_requirements(build_generation_ledger(scope_body(kind, parameters)), package)
    return next(item['passed'] for item in result['checks'] if item['requirementId'] == 'scope')


@pytest.mark.parametrize('entries,expected', [
    ([{'requirementId': 'a'}, {'requirementId': 'b'}], True),
    ([{'requirementId': 'b'}, {'requirementId': 'a'}], True),
    ([{'requirementId': 'a'}, {'requirementId': 'b'}, {'requirementId': 'c'}], False),
    ([{'requirementId': 'a'}], False),
    ([{'requirementId': 'a'}, {'requirementId': 'a'}], False),
    ([{'requirementId': []}, {'requirementId': 'b'}], False),
    ([None, {'requirementId': 'b'}], False),
    (None, False),
])
def test_exact_resource_set_rejects_extras_missing_and_duplicate_batches(entries, expected):
    assert scope_passes('resource_set', {'requirementIds': ['a', 'b']}, {'equipmentRequirements': entries}) is expected


@pytest.mark.parametrize('routes,count,expected', [([], 0, True), ([{}], 0, False),
    ([], 1, False), ([{}], 1, True), (None, 0, False), (['bad-route'], 1, False)])
def test_exact_route_count(routes, count, expected):
    assert scope_passes('route_count', {'count': count}, {'routes': routes}) is expected


@pytest.mark.parametrize('nested', ['cellRecipes', 'moduleFamilies'])
def test_flat_scope_does_not_claim_coverage_for_future_nested_resources(nested):
    package = {'equipmentRequirements': [{'requirementId': 'a'}], 'routes': [], nested: [{}]}
    assert not scope_passes('resource_set', {'requirementIds': ['a']}, package)
    assert not scope_passes('route_count', {'count': 0}, package)


@pytest.mark.parametrize('kind,parameters', [
    ('resource_set', {'requirementIds': []}),
    ('resource_set', {'requirementIds': ['a', 'a']}),
    ('resource_set', {'requirementIds': ['a'] * 25}),
    ('resource_set', {'requirementIds': ['a'], 'allowExtras': True}),
    ('route_count', {'count': True}), ('route_count', {'count': -1}),
    ('route_count', {'count': 33}), ('route_count', {'count': '0'}),
])
def test_scope_predicates_are_closed_and_bounded(kind, parameters):
    with pytest.raises(GenerationRequirementError):
        build_generation_ledger(scope_body(kind, parameters))


@pytest.mark.parametrize('kind,parameters', [('resource_set', {'requirementIds': ['a']}), ('route_count', {'count': 0})])
def test_scope_requires_the_exact_layout_identity(kind, parameters):
    value = scope_body(kind, parameters)
    value['requirements'][-1]['predicate']['subjectId'] = 'another-layout'
    with pytest.raises(GenerationRequirementError) as error:
        build_generation_ledger(value)
    assert error.value.code == 'generation_requirement_subject_invalid'


def test_duplicate_clauses_allow_equivalent_resource_set_order_but_not_conflicts():
    value = scope_body('resource_set', {'requirementIds': ['a', 'b']})
    copy = deepcopy(value['requirements'][-1])
    copy['requirementId'] = 'scope-repeated'
    copy['predicate']['parameters']['requirementIds'] = ['b', 'a']
    value['requirements'].append(copy)
    build_generation_ledger(value)
    copy['predicate']['parameters']['requirementIds'] = ['a', 'c']
    with pytest.raises(GenerationRequirementError) as error:
        build_generation_ledger(value)
    assert error.value.code == 'generation_requirement_conflict'


def test_build_guidance_is_bounded_independent_and_not_a_factory_fixture():
    summary = build_method_summary()
    assert summary['currentLimits']['placements'] == 900
    assert summary['currentLimits']['cellRecipes'] is True
    stages = build_method_stages()
    assert len(stages) == 6
    assert len(json.dumps(stages).encode()) < 10000
    assert all(not s['tools'] for s in stages if s['availability'] == 'not_integrated_in_generation_chat')
    assert 'fl-independent' not in json.dumps(stages)
    assert 'Factory 02' not in json.dumps(stages)
    stages[0]['method'].clear()
    assert build_method_stages()[0]['method']


def test_real_context_exposes_paginated_method_without_mutating_layout(chat):
    before = deepcopy(chat['binding'])
    overview = execute(chat, CONTEXT_TOOL, {})
    assert overview['buildMethod'] == build_method_summary()
    first = execute(chat, CONTEXT_TOOL, {'section': 'buildMethod', 'limit': 2})
    second = execute(chat, CONTEXT_TOOL, {'section': 'buildMethod', 'offset': 2, 'limit': 4})
    assert first['nextOffset'] == 2 and second['nextOffset'] is None
    assert first['items'] + second['items'] == build_method_stages()
    assert first['total'] == 6
    assert chat['binding'] == before
    for tool in {t for stage in build_method_stages() for t in stage['tools']}:
        assert tool in {spec['name'] for spec in generation_tool_specs()}


def add_scope_clauses(chat, route_count=None):
    ids = [item['requirementId'] for item in chat['request']['proposal']['equipmentRequirements']]
    count = len(chat['request']['proposal']['routes']) if route_count is None else route_count
    for key, text, parameters in (
        ('resource_set', 'Use only these equipment batches and no additional equipment.', {'requirementIds': ids}),
        ('route_count', f'Create exactly {count} routes.', {'count': count}),
    ):
        chat['message'] += ' ' + text
        chat['record']['requirements'].append({
            'requirementId': key, 'sourceText': text, 'kind': 'hard_constraint',
            'predicate': {'kind': key, 'subjectId': chat['binding']['layoutId'], 'parameters': parameters},
        })


def test_real_kernel_exact_scope_repairs_extra_equipment_without_waiving_ledger(chat):
    add_scope_clauses(chat)
    ledger = execute(chat, REQUIREMENTS_TOOL, chat['record'])
    proposal = deepcopy(chat['request']['proposal'])
    extra = deepcopy(proposal['equipmentRequirements'][0])
    extra['requirementId'] = 'unrequested-extra'
    proposal['equipmentRequirements'].append(extra)
    args = {'requestKey': 'scope-extra', 'expectedLedgerRevision': ledger['ledgerRevision'], 'proposal': proposal}
    assert_code('generation_requirements_not_satisfied', lambda: execute(chat, PREVIEW_TOOL, args))
    args['proposal'] = deepcopy(chat['request']['proposal'])
    args['requestKey'] = 'scope-corrected'
    result = execute(chat, PREVIEW_TOOL, args)
    assert result['counts']['placements'] == 2
    assert result['counts']['routes'] == len(args['proposal']['routes'])
    assert execute(chat, PREVIEW_TOOL, args) == result
    saved = chat['host'].service.get_layout(chat['principal'], **{
        key: chat['options'][key] for key in ('site_id', 'layout_id')})
    assert saved['revision'] == chat['ledger']['baseRevision']


def test_no_routes_constraint_rejects_a_package_with_routes(chat):
    add_scope_clauses(chat, route_count=0)
    ledger = execute(chat, REQUIREMENTS_TOOL, chat['record'])
    args = {'requestKey': 'forbidden-route', 'expectedLedgerRevision': ledger['ledgerRevision'],
            'proposal': chat['request']['proposal']}
    assert_code('generation_requirements_not_satisfied', lambda: execute(chat, PREVIEW_TOOL, args))


def test_gateway_lowered_schema_supports_scope_without_accepting_invalid_counts():
    import jsonschema
    from ai_inspector.model_gateway import explicit_named_properties
    from ai_inspector.facility_layout.generation_agent import _predicate_schema
    schema = _predicate_schema()
    lowered = explicit_named_properties(schema)
    for kind, parameters, valid in (
        ('resource_set', {'requirementIds': ['benches']}, True),
        ('resource_set', {'requirementIds': ['benches', 'benches']}, False),
        ('route_count', {'count': 0}, True), ('route_count', {'count': True}, False),
        ('route_count', {'count': -1}, False),
    ):
        request = {'kind': kind, 'subjectId': 'fl-target', 'parameters': parameters}
        for definition in (schema, lowered):
            assert jsonschema.Draft202012Validator(definition).is_valid(request) is valid
