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
