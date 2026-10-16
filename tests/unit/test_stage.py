from scripts.stage import MAX_LENGTH, stage_from_branch


def test_short_branch_names_are_normalized() -> None:
    assert stage_from_branch("Feature/Foo_Bar") == "feature-foo-bar"


def test_long_branch_names_are_shortened_with_a_hash() -> None:
    first = stage_from_branch("claude/very-long-branch-name-one")
    second = stage_from_branch("claude/very-long-branch-name-two")

    assert len(first) <= MAX_LENGTH and len(second) <= MAX_LENGTH
    assert first != second
    assert first.startswith("claude-very-")


def test_only_valid_characters() -> None:
    assert stage_from_branch("--Ä!!--") == "stage"
