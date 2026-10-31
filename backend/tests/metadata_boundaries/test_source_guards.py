"""Mutate actual writer ASTs to prove the structural fence detects regressions.

Only the standalone stdlib validator is loaded; no Django/app initialization or
database is needed for these tests. Each mutation first validates pristine source.
"""
import ast
from copy import deepcopy
from pathlib import Path
import runpy

import pytest

APPS = Path(__file__).resolve().parents[2] / "apps"
PROFILE = "apps.makerspaces.profile_services.save_profile"
TYPED = "apps.machines.public_service_intake.submit_typed_request"
PRINTER = "apps.machines.public_printer_service.submit_request"
SERIES = "apps.events.services_series.update_series"
INNER = "apps.events.services_series._update_series"
BULK = "apps.admin_api.bulk_import_apply.apply_import"
WRITERS = (PROFILE, TYPED, PRINTER, SERIES, BULK)


class BoundaryDrift(Exception):
    pass


def validator():
    return runpy.run_path(str(APPS / "tenant_migration/source_gate_conditional_guards.py"))


def functions():
    result = {}
    for target in (*WRITERS, INNER):
        module, name = target.rsplit(".", 1)
        path = APPS.joinpath(*module.split(".")[1:]).with_suffix(".py")
        tree = ast.parse(path.read_text())
        node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
        result[target] = node
    return result


def pristine():
    api, nodes = validator(), functions()
    api["validate_conditional_service_boundaries"](nodes, BoundaryDrift)
    return api, deepcopy(nodes)


def shape(node):
    return ast.dump(node, include_attributes=False)


def expression(text):
    return ast.parse(text, mode="eval").body


def replace(node, old, new, *, count=1):
    expected, replacement, hits = shape(expression(old)), expression(new), []
    class Replace(ast.NodeTransformer):
        def generic_visit(self, item):
            if shape(item) == expected:
                hits.append(item)
                return deepcopy(replacement)
            return super().generic_visit(item)
    Replace().visit(node)
    assert len(hits) == count, f"mutation no longer targets real source: {old} ({len(hits)})"


def context(node):
    return next(item for item in ast.walk(node) if isinstance(item, ast.With)
                and shape(item.items[0].context_expr) == shape(expression("context")))


def atomic(scope):
    return next(item for item in scope.body if isinstance(item, ast.With)
                and shape(item.items[0].context_expr) == shape(expression("transaction.atomic()")))


def unwrap(scope, node):
    index = scope.body.index(node)
    scope.body[index:index + 1] = node.body


def test_actual_conditional_writer_baseline_and_explicit_registration():
    api, _nodes = pristine()
    assert set(api["CONDITIONAL_WRITER_BOUNDARIES"]) == set(WRITERS)
    tree = ast.parse((APPS / "tenant_migration/source_gate_service_guards.py").read_text())
    registry = next(item.value for item in tree.body if isinstance(item, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "SERVICE_WRITER_BOUNDARIES" for target in item.targets))
    assert set(WRITERS) <= ast.literal_eval(registry).keys()
    assert any(isinstance(call, ast.Call) and getattr(call.func, "id", None) == "validate_conditional_service_boundaries"
               for call in ast.walk(tree))


@pytest.mark.parametrize("target", WRITERS)
def test_missing_writer_fails_closed(target):
    api, nodes = pristine()
    del nodes[target]
    with pytest.raises(BoundaryDrift, match="missing entrypoint"):
        api["validate_conditional_service_boundaries"](nodes, BoundaryDrift)


EXPRESSION_MUTATIONS = [
    (PROFILE, '"projects" in data', 'data.get("projects")', 2),
    (PROFILE, "tenant_write(membership.makerspace_id)", "nullcontext(None)", 1),
    (PROFILE, 'save_projects(profile, data["projects"], guard=guard)', 'save_projects(profile, data["projects"])', 1),
    (SERIES, "set(changes) & RECURRENCE_FIELDS", "any(getattr(series, key) != value for key, value in changes.items() if key in RECURRENCE_FIELDS)", 1),
    (SERIES, "boundary_tenant_write(series.makerspace_id)", "nullcontext(None)", 1),
    (SERIES, "_update_series(series, actor=actor, effective_from=effective_from, guard=guard, **changes)", "_update_series(series, actor=actor, effective_from=effective_from, **changes)", 1),
    (BULK, 'any(item["action"] != "error" and item["data"].get("image_key", "") for item in preview["rows"])', 'any(item["action"] != "error" and item["data"].get("image_key", "") and item["action"] != "update" for item in preview["rows"])', 1),
    (BULK, "nullcontext(None)", "boundary_tenant_write(makerspace.pk)", 1),
    (BULK, 'item["action"] == "error" or not key', 'item["action"] == "error"', 1),
    (BULK, '_apply_import_row(actor, makerspace, item, preview["mapping"], prepared.get(item["row"]), guard)', '_apply_import_row(actor, makerspace, item, preview["mapping"], prepared.get(item["row"]), None)', 1),
]
for target in (TYPED, PRINTER):
    EXPRESSION_MUTATIONS.extend([
        (target, 'tuple(data.get("file_ids") or ())', 'data.get("file_ids") or []', 1),
        (target, "boundary_tenant_write(makerspace.pk)", "nullcontext(None)", 1),
        (target, "prepare_files(makerspace.pk, ids, actor, guard)", 'prepare_files(makerspace.pk, data["file_ids"], actor, guard)', 1),
        (target, "finalize_file(row, file_id=file.pk, actor=actor, guard=guard, prepared=prepared[file.pk])", "finalize_file(row, file_id=file.pk, actor=actor, prepared=prepared[file.pk])", 1),
    ])
EXPRESSION_MUTATIONS.extend([
    (TYPED, "lock_attachments(space, actor, ids, queue)", 'lock_attachments(space, actor, data["file_ids"], queue)', 1),
    (PRINTER, "len(files) != len(set(ids))", 'len(files) != len(set(data["file_ids"]))', 1),
])


@pytest.mark.parametrize("target,old,new,count", EXPRESSION_MUTATIONS,
                         ids=[f"{target.rsplit('.', 1)[-1]}-{index}" for index, (target, *_rest) in enumerate(EXPRESSION_MUTATIONS)])
def test_independent_expression_regressions_fail(target, old, new, count):
    api, nodes = pristine()
    replace(nodes[target], old, new, count=count)
    with pytest.raises(BoundaryDrift):
        api["validate_conditional_service_boundaries"](nodes, BoundaryDrift)


STRUCTURAL_MUTATIONS = [
    (PROFILE, "project-outside-presence"),
    (PROFILE, "remove-atomic"),
    (SERIES, "unconditional-verify"),
    (SERIES, "remove-atomic"),
    (BULK, "unconditional-verify"),
    (BULK, "remove-outer-boundary"),
    (BULK, "preview-progress-outside-boundary"),
    (BULK, "prepare-inside-atomic"),
    (BULK, "remove-atomic"),
]
for target in (TYPED, PRINTER):
    STRUCTURAL_MUTATIONS.extend((target, mutation) for mutation in (
        "unconditional-verify", "prepare-inside-atomic", "iterate-ids-instead-of-locked-files", "remove-atomic",
    ))


def structural_mutation(nodes, target, mutation):
    node = nodes[target]
    owned = context(node)
    if mutation == "remove-atomic":
        if target == SERIES:
            nodes[INNER].decorator_list = []
        else:
            unwrap(owned, atomic(owned))
    elif mutation == "project-outside-presence":
        inner = atomic(owned)
        branch = next(item for item in inner.body if isinstance(item, ast.If)
                      and shape(item.test) == shape(expression('"projects" in data')))
        unwrap(inner, branch)
    elif mutation == "unconditional-verify":
        # For intakes keep preparation conditional but move verification out.
        branch = next(item for item in owned.body if isinstance(item, ast.If)
                      and any(isinstance(call, ast.Call) and getattr(call.func, "attr", None) == "verify" for call in ast.walk(item)))
        if target in (TYPED, PRINTER):
            verify = branch.body.pop()
            owned.body.insert(owned.body.index(branch) + 1, verify)
        else:
            unwrap(owned, branch)
    elif mutation == "remove-outer-boundary":
        unwrap(node, node.body[0])
    elif mutation == "preview-progress-outside-boundary":
        outer = node.body[0]
        node.body.insert(0, outer.body.pop(0))
    elif mutation == "prepare-inside-atomic":
        preparation = next(item for item in owned.body
                           if isinstance(item, ast.For if target == BULK else ast.If)
                           and any(isinstance(call, ast.Call) and getattr(call.func, "id", None)
                                   == ("finalize_product_image" if target == BULK else "prepare_files")
                                   for call in ast.walk(item)))
        owned.body.remove(preparation)
        atomic(owned).body.insert(0, preparation)
    elif mutation == "iterate-ids-instead-of-locked-files":
        loop = next(item for item in ast.walk(atomic(owned)) if isinstance(item, ast.For))
        loop.iter = expression("ids")
    else:
        raise AssertionError(mutation)


@pytest.mark.parametrize("target,mutation", STRUCTURAL_MUTATIONS,
                         ids=[f"{target.rsplit('.', 1)[-1]}-{mutation}" for target, mutation in STRUCTURAL_MUTATIONS])
def test_independent_scope_order_and_ownership_regressions_fail(target, mutation):
    api, nodes = pristine()
    structural_mutation(nodes, target, mutation)
    with pytest.raises(BoundaryDrift):
        api["validate_conditional_service_boundaries"](nodes, BoundaryDrift)
