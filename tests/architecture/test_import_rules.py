"""Import rules PyTestArch enforces.

The domain's own pyproject.toml does not prevent a boto3 import: locally all workspace packages
share one .venv, and the Lambda runtime ships boto3 anyway. Only these rules catch it.
"""

from pathlib import Path

import pytest
from pytestarch import EvaluableArchitecture, Rule, get_evaluable_architecture

REPO = Path(__file__).resolve().parents[2]
SERVICE = REPO / "services" / "workshops"
DOMAIN = SERVICE / "workshop_service_domain" / "src" / "workshop_service_domain"
INFRA = SERVICE / "workshop_service_infra" / "src" / "workshop_service_infra"
FUNCTIONS = SERVICE / "functions" / "src" / "functions"
TESTS = REPO / "tests"

AWS_SDK = ["boto3", "botocore"]
# Part 2 adds "sqlmodel" and "sqlalchemy" here.
PERSISTENCE_LIBRARIES = [*AWS_SDK]


def architecture(package: Path) -> EvaluableArchitecture:
    # The package directory is the root, so module names equal import names
    # (`workshop_service_domain.models`) and imports of other packages resolve to them.
    return get_evaluable_architecture(
        package, package, exclusions=("*__pycache__*",), exclude_external_libraries=False
    )


def assert_no_imports(arch: EvaluableArchitecture, package: str, forbidden: list[str]) -> None:
    """`package` and its sub-modules import none of `forbidden` or their sub-modules.

    PyTestArch refuses rules on modules that nothing in the scanned tree imports, which is the
    normal case for a forbidden module. Those are left out: nothing imports them, so the rule
    holds. The moment someone adds the import, the module is in the graph and the rule applies.
    """
    imported = [
        name
        for name in forbidden
        if any(m == name or m.startswith(f"{name}.") for m in arch.modules)
    ]
    if not imported:
        return
    for select in ("are_named", "are_sub_modules_of"):
        for importer in ("are_named", "are_sub_modules_of"):
            rule = getattr(Rule().modules_that(), importer)(package)
            getattr(rule.should_not().import_modules_that(), select)(imported).assert_applies(arch)


@pytest.fixture(scope="module")
def tests() -> EvaluableArchitecture:
    return architecture(TESTS)


def test_domain_has_no_infrastructure_imports() -> None:
    assert_no_imports(
        architecture(DOMAIN),
        "workshop_service_domain",
        [*PERSISTENCE_LIBRARIES, "workshop_service_infra", "functions"],
    )


def test_infra_does_not_import_functions() -> None:
    assert_no_imports(architecture(INFRA), "workshop_service_infra", ["functions"])


def test_only_functions_api_imports_infra() -> None:
    # The domain is covered above. Here: nothing in functions outside functions.api.
    arch = architecture(FUNCTIONS)
    outside_api = sorted(
        m for m in arch.modules if m.startswith("functions.") and not m.startswith("functions.api")
    )
    for module in outside_api:
        assert_no_imports(arch, module, ["workshop_service_infra"])


def test_unit_tests_stay_with_fakes(tests: EvaluableArchitecture) -> None:
    assert_no_imports(
        tests,
        "tests.unit",
        # All of unittest: `from unittest import mock` only shows up as an import of `unittest`.
        [*AWS_SDK, "moto", "unittest", "freezegun", "workshop_service_infra"],
    )
