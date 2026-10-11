"""Reconcile tables created by older application startup code.

Only skip a table creation when the existing table has the columns and key
constraints expected by that migration. Never discard existing data.
"""

import sqlalchemy as sa
from alembic import op


def _inspector():
    return sa.inspect(op.get_bind())


def _constraint_columns(constraint):
    # A constraint passed to op.create_table has not been attached to a Table.
    return tuple(constraint._pending_colargs)


def create_table(name, *elements, **kwargs):
    inspector = _inspector()
    if not inspector.has_table(name):
        return op.create_table(name, *elements, **kwargs)

    actual = {column["name"]: column for column in inspector.get_columns(name)}
    expected = [element for element in elements if isinstance(element, sa.Column)]
    missing = [column.name for column in expected if column.name not in actual]
    if missing:
        raise RuntimeError(f"Existing {name} is missing columns: {', '.join(missing)}")

    expected_pk = {column.name for column in expected if column.primary_key}
    for element in elements:
        if isinstance(element, sa.PrimaryKeyConstraint):
            expected_pk.update(_constraint_columns(element))
    actual_pk = set(inspector.get_pk_constraint(name).get("constrained_columns") or [])
    if expected_pk != actual_pk:
        raise RuntimeError(f"Existing {name} has an unexpected primary key")

    for column in expected:
        actual_column = actual[column.name]
        # A later migration intentionally makes this column nullable. A table
        # created directly from the current ORM can already have that shape.
        later_nullable = name == "sequence_deliveries" and column.name == "step_id"
        if not column.nullable and actual_column["nullable"] and not column.primary_key and not later_nullable:
            raise RuntimeError(f"Existing {name}.{column.name} must be NOT NULL")
        if isinstance(column.type, sa.String):
            found_type = actual_column["type"]
            if not isinstance(found_type, sa.String) or (
                column.type.length is not None and found_type.length != column.type.length
            ):
                raise RuntimeError(f"Existing {name}.{column.name} has an unexpected type")

    uniques = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(name)}
    for element in elements:
        if isinstance(element, sa.UniqueConstraint):
            columns = _constraint_columns(element)
            # This uniqueness is removed by the enrollment-runs migration.
            later_removed = name == "sequence_enrollments" and columns == ("sequence_id", "lead_id")
            if columns not in uniques and not later_removed:
                raise RuntimeError(f"Existing {name} is missing unique constraint on {columns}")


def create_index(name, table, columns, **kwargs):
    indexes = {item["name"]: item for item in _inspector().get_indexes(table)}
    if name not in indexes:
        return op.create_index(name, table, columns, **kwargs)
    if indexes[name]["column_names"] != list(columns):
        raise RuntimeError(f"Existing index {name} has unexpected columns")
