"""Initial migration

Revision ID: 7561157b75e2
Revises: 91ea88e76dfe
Create Date: 2026-08-06 12:04:07.375765

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7561157b75e2'
down_revision: Union[str, None] = '91ea88e76dfe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.alter_column(

        "threads",

        "last_message_id",

        existing_type=sa.TEXT(),

        type_=sa.Integer(),

        existing_nullable=True,

        postgresql_using="last_message_id::integer",

    )

def downgrade() -> None:

    op.alter_column(

        "threads",

        "last_message_id",

        existing_type=sa.Integer(),

        type_=sa.TEXT(),

        existing_nullable=True,

        postgresql_using="last_message_id::text",

    )
