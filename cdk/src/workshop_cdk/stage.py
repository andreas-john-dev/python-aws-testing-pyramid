from dataclasses import dataclass

from aws_cdk import RemovalPolicy

PRODUCTION_STAGES = frozenset({"prod"})


@dataclass(frozen=True)
class Stage:
    name: str

    @property
    def is_production(self) -> bool:
        return self.name in PRODUCTION_STAGES

    @property
    def removal_policy(self) -> RemovalPolicy:
        # DESTROY only for short-lived stages, e.g. one per branch.
        return RemovalPolicy.RETAIN if self.is_production else RemovalPolicy.DESTROY

    def stack_name(self, kind: str) -> str:
        return f"workshops-{self.name}-{kind}"
