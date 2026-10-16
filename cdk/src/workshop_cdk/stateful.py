from aws_cdk import Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ssm as ssm
from constructs import Construct
from workshop_service_infra import parameters, schema

from workshop_cdk.stage import Stage


def _string_key(name: str) -> dynamodb.Attribute:
    return dynamodb.Attribute(name=name, type=dynamodb.AttributeType.STRING)


class StatefulStack(Stack):
    """The workshops table. Key names and the GSI come from schema.py, like in the moto fixture."""

    def __init__(self, scope: Construct, stage: Stage, **kwargs: object) -> None:
        super().__init__(scope, stage.stack_name("stateful"), **kwargs)

        table = dynamodb.TableV2(
            self,
            "Table",
            # The stage in the name allows resource patterns (table/workshops-*) in the policies
            # of the developer and pipeline roles.
            table_name=f"workshops-{stage.name}",
            partition_key=_string_key(schema.PARTITION_KEY),
            sort_key=_string_key(schema.SORT_KEY),
            billing=dynamodb.Billing.on_demand(),
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=stage.is_production
            ),
            removal_policy=stage.removal_policy,
            global_secondary_indexes=[
                dynamodb.GlobalSecondaryIndexPropsV2(
                    index_name=schema.GSI1_NAME,
                    partition_key=_string_key(schema.GSI1_PARTITION_KEY),
                    sort_key=_string_key(schema.GSI1_SORT_KEY),
                    projection_type=dynamodb.ProjectionType(schema.GSI1_PROJECTION),
                )
            ],
        )
        ssm.StringParameter(
            self,
            "TableNameParameter",
            parameter_name=parameters.name(stage.name, parameters.TABLE_NAME),
            string_value=table.table_name,
        )
