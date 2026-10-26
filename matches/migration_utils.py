from django.db import migrations


class AddFieldIfMissing(migrations.AddField):
    """AddField that skips the ALTER TABLE when the column already exists.

    Production ended up with some organiser-fee columns created outside the
    normal migration flow, so a plain AddField fails with DuplicateColumn.
    """

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        to_model = to_state.apps.get_model(app_label, self.model_name)
        column = to_model._meta.get_field(self.name).column
        connection = schema_editor.connection
        with connection.cursor() as cursor:
            existing = {
                col.name
                for col in connection.introspection.get_table_description(
                    cursor, to_model._meta.db_table
                )
            }
        if column in existing:
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)
