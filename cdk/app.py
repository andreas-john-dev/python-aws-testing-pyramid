"""CDK app. `cdk deploy --all -c stage=<stage>` deploys shared, stateful and stateless.

The ci stack is only part of the app with `-c github_repository=<owner/repo>`.
"""

import aws_cdk as cdk
from workshop_cdk.ci import CI_STACK_NAME, CiStack
from workshop_cdk.oidc import discover_provider
from workshop_cdk.shared import SharedStack
from workshop_cdk.stage import Stage
from workshop_cdk.stateful import StatefulStack
from workshop_cdk.stateless import StatelessStack

app = cdk.App()
env = cdk.Environment(
    account=app.node.try_get_context("account") or None,
    region=app.node.try_get_context("region") or None,
)

github_repository = app.node.try_get_context("github_repository")
if github_repository:
    CiStack(
        app,
        github_repository=github_repository,
        oidc_provider_arn=discover_provider(
            CI_STACK_NAME, app.node.try_get_context("oidc_provider_arn")
        ),
        env=env,
    )
else:
    stage_name = app.node.try_get_context("stage")
    if not stage_name:
        raise SystemExit("pass -c stage=<stage>, e.g. via `make deploy`")
    stage = Stage(stage_name)
    shared = SharedStack(app, stage, env=env)
    stateful = StatefulStack(app, stage, env=env)
    stateless = StatelessStack(app, stage, env=env)
    # The stateless stack resolves the SSM parameters of the other two at deploy time.
    stateless.add_stack_dependency(shared)
    stateless.add_stack_dependency(stateful)
    cdk.Tags.of(app).add("stage", stage.name)

app.synth()
