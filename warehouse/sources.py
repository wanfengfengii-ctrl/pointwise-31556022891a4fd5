from .catalog import Catalog
from .validation import validate_source_request, validate_source_rows
from .revisions import RevisionRepository


class SourceService:
    def __init__(self, database):
        self.catalog = Catalog(database)
        self.revisions = RevisionRepository(database)

    def apply_source(self, request_id, dataset, rows):
        validate_source_request(request_id, dataset)
        schema = self.catalog.get_schema(dataset)
        normalized = validate_source_rows(schema, rows)
        return self.revisions.commit_revision(request_id, schema, normalized)
