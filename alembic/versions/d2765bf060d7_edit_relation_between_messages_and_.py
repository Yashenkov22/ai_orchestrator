"""edit relation between Messages and Attachments

Revision ID: d2765bf060d7
Revises: 51b07621c9ef
Create Date: 2026-05-28 13:35:06.559755

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd2765bf060d7'
down_revision: Union[str, None] = '51b07621c9ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.drop_constraint(

        "attachments_message_id_key",

        "attachments",

        type_="unique"

    )

def downgrade():

    op.create_unique_constraint(

        "attachments_message_id_key",

        "attachments",

        ["message_id"]

    )