# PostgreSQL Backup and Restore Runbook

## Policy

- Enable Railway Daily backups for the production PostgreSQL volume.
- Keep the Railway default daily retention of 6 days.
- Enable Weekly backups for one-month retention after moving to a paid plan.
- Create a manual locked backup before schema changes, data imports, or destructive maintenance.
- Export a logical `pg_dump` outside Railway before high-risk migrations.
- Never commit database dumps, credentials, or `DATABASE_URL` to Git.

## Current Railway State

The production service is `Postgres-bWm0` in the `production` environment.
As of 2026-07-19 the Railway workspace is on Trial and the service Backups tab
renders without backup controls. Scheduling therefore requires resolving the
Railway plan or UI limitation before this policy can become active.

## Enable Native Backups

1. Upgrade the Railway workspace if the Backups controls remain unavailable on Trial.
2. Open `Postgres-bWm0` and select **Backups**.
3. Enable **Daily** and verify that the retention shown is 6 days.
4. Enable **Weekly** and verify that the retention shown is 1 month.
5. Create one manual backup and verify that it appears with a successful timestamp.
6. Record the first successful backup time in the operations log.

Railway backups are incremental volume snapshots. Wiping the volume deletes its
backups, and a native backup can only be restored in the same project and environment.

## Restore Rehearsal

Do not restore over the active production service during a rehearsal.

1. Select a backup in the PostgreSQL **Backups** tab and choose **Restore**.
2. Railway stages a restored volume; review the staged changes before deployment.
3. Deploy the restored volume only in a maintenance window or isolated rehearsal environment.
4. Point a temporary application service at the restored database.
5. Verify `/health`, `/ready`, game count 51, alias count 118, relation count 6, and quality score 100.
6. Run the PostgreSQL contract tests against the restored database.
7. Remove the temporary application and restored volume after approval.

## Logical Backup Before Destructive Work

Use a workstation or approved backup runner with PostgreSQL client tools installed:

```powershell
pg_dump --format=custom --no-owner --no-acl --file boardgame-production.dump $env:DATABASE_URL
pg_restore --list boardgame-production.dump
```

Store the dump in an approved external location, generate a SHA-256 checksum, and
delete local and Railway temporary copies after retention requirements are met.

## Recovery Objectives

- Target RPO: 24 hours while Daily backups are the primary recovery mechanism.
- Target RTO: 2 hours for restore, validation, and application cutover.
- Rehearse restoration monthly and after material schema changes.
