from unittest.mock import Mock

import pytest
import sqlalchemy as sa

from migrations import schema_compat


def _inspector(columns, *, pk=("id",), uniques=(), indexes=()):
    inspector = Mock()
    inspector.has_table.return_value = True
    inspector.get_columns.return_value = [
        {"name": name, "nullable": nullable, "type": kind}
        for name, nullable, kind in columns
    ]
    inspector.get_pk_constraint.return_value = {"constrained_columns": list(pk)}
    inspector.get_unique_constraints.return_value = [
        {"column_names": list(columns)} for columns in uniques
    ]
    inspector.get_indexes.return_value = [
        {"name": name, "column_names": list(columns)} for name, columns in indexes
    ]
    return inspector


def test_existing_compatible_table_is_preserved(monkeypatch):
    inspector = _inspector(
        [("id", False, sa.UUID()), ("email", False, sa.VARCHAR(320))],
        uniques=[("email",)],
    )
    monkeypatch.setattr(schema_compat, "_inspector", lambda: inspector)
    create = Mock()
    monkeypatch.setattr(schema_compat.op, "create_table", create)

    schema_compat.create_table(
        "example",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.UniqueConstraint("email", name="uq_example_email"),
    )
    create.assert_not_called()


def test_existing_incomplete_table_fails_closed(monkeypatch):
    monkeypatch.setattr(schema_compat, "_inspector", lambda: _inspector([("id", False, sa.UUID())]))
    with pytest.raises(RuntimeError, match="missing columns: email"):
        schema_compat.create_table(
            "example",
            sa.Column("id", sa.UUID(), primary_key=True),
            sa.Column("email", sa.String(320), nullable=False),
        )


def test_existing_index_is_not_recreated(monkeypatch):
    inspector = _inspector([], indexes=[("ix_example_email", ("email",))])
    monkeypatch.setattr(schema_compat, "_inspector", lambda: inspector)
    create = Mock()
    monkeypatch.setattr(schema_compat.op, "create_index", create)
    schema_compat.create_index("ix_example_email", "example", ["email"])
    create.assert_not_called()


def test_later_sequence_changes_are_accepted(monkeypatch):
    inspector = _inspector(
        [("id", False, sa.UUID()), ("sequence_id", False, sa.UUID()), ("lead_id", False, sa.UUID())]
    )
    monkeypatch.setattr(schema_compat, "_inspector", lambda: inspector)
    schema_compat.create_table(
        "sequence_enrollments",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("sequence_id", sa.UUID(), nullable=False),
        sa.Column("lead_id", sa.UUID(), nullable=False),
        sa.UniqueConstraint("sequence_id", "lead_id", name="uq_sequence_lead_enrollment"),
    )


def test_other_missing_unique_constraint_still_fails(monkeypatch):
    inspector = _inspector([("id", False, sa.UUID()), ("email", False, sa.VARCHAR(320))])
    monkeypatch.setattr(schema_compat, "_inspector", lambda: inspector)
    with pytest.raises(RuntimeError, match="missing unique constraint"):
        schema_compat.create_table(
            "example",
            sa.Column("id", sa.UUID(), primary_key=True),
            sa.Column("email", sa.String(320), nullable=False),
            sa.UniqueConstraint("email", name="uq_example_email"),
        )
