# rmn-common

The pieces of the contract between the server, the executor and the webapp that
used to be copied into each service (and had started to drift):

- `rmn_common.status`: `Job_Status`, `Document_Status`, `Output_File`, `User_Role`
  as stored in MongoDB and compared by the webapp.
- `rmn_common.questions`: the `Q<n>` question keys (validation, numeric sort,
  ignored questions).
- `rmn_common.moodle`: the column names of a Moodle grades csv.
- `rmn_common.paths`: file-name safety for values coming from a csv.
- `rmn_common.storage`: the per-job layout of the shared storage and the
  `Storage` class both services build on.
- `rmn_common.typescript`: renders the enums of `rmn_common.status` to
  `services/webapp/ng/src/app/generated/rmn-contracts.ts` (`JobStatus`,
  `DocumentStatus`, `OutputFile`, `UserRole`), the webapp's only copy of the
  values it compares. Run `python -m rmn_common.typescript` after changing a
  status; the tests here and the webapp CI job run it with `--check`.

No third-party dependency. Each service installs it from the repo:

```
pip install -r requirements-dev.txt      # includes `-e ../common`
```

The Docker images copy it from the `services/` build context (see the
Dockerfiles). Tests: `pip install -e . pytest && python -m pytest` in this
directory; the CI runs them, and the server and executor suites, whenever this
package changes.

Changing a stored value is a migration: `Document_Status.NOT_READY` became
`"NOT READY"` (was `"NOT_READY"`), so documents of jobs in progress at the
upgrade need, in the `RMN` database:

```
db.job_documents.updateMany({status: "NOT_READY"}, {$set: {status: "NOT READY"}})
```
