from workshop_cdk.ci import subject_prefix
from workshop_cdk.oidc import choose_provider

EXISTING = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"


def test_creates_the_provider_in_a_fresh_account() -> None:
    assert choose_provider(None, stack_owns_provider=False, existing_arn=None) is None


def test_references_a_provider_someone_else_created() -> None:
    assert choose_provider(None, stack_owns_provider=False, existing_arn=EXISTING) == EXISTING


def test_keeps_creating_a_provider_the_stack_owns() -> None:
    # Referencing it now would make CloudFormation delete it.
    assert choose_provider(None, stack_owns_provider=True, existing_arn=EXISTING) is None


def test_an_explicit_arn_wins() -> None:
    assert choose_provider("arn:x", stack_owns_provider=True, existing_arn=None) == "arn:x"


def test_subject_prefix_defaults_to_owner_and_repository() -> None:
    assert subject_prefix("octo/repo", None) == "repo:octo/repo"


def test_subject_prefix_uses_the_immutable_prefix_github_reports() -> None:
    reported = "repo:octo@1/repo@2"
    assert subject_prefix("octo/repo", reported) == reported
