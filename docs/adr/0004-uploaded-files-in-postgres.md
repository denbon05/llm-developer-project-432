# Uploaded supplier documents are stored in PostgreSQL

**Status:** accepted

The API receives a supplier document, but the worker parses it in another
process, and a Temporal payload can't carry the file: payloads are limited to
about 2 MB and kept in the workflow history.

We store the file's bytes in the document's row as `bytea`, with a 10 MiB
upload limit. The row, its bytes and the content hash that catches duplicate
uploads live in one store, and a database reset clears them together.

The alternatives were a shared directory, which both processes would have to
mount, and object storage, the usual choice for large files in production,
which would add a service to run and keep in sync. Moving to object storage
later changes only the documents repository and the upload path.
