"""add json column

Revision ID: 58d71214c327
Revises: 0a7137e18b0c
Create Date: 2019-10-03 17:19:14.180702

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '58d71214c327'
down_revision = '8d0c21474c48'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('property', sa.Column('prop_json', sa.JSON(), nullable=True))
    op.drop_constraint('property_check', 'property')
    op.create_check_constraint('property_check', 'property', 'NOT(prop_resource IS NULL AND prop_string IS NULL AND prop_datetime IS NULL AND prop_integer IS NULL AND prop_url IS NULL AND prop_json IS NULL)'),
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('property_check', 'property')
    op.create_check_constraint('property_check', 'property', 'NOT(prop_resource IS NULL AND prop_string IS NULL AND prop_datetime IS NULL AND prop_integer IS NULL AND prop_url IS NULL)'),
    op.drop_column('property', 'prop_json')
    # ### end Alembic commands ###