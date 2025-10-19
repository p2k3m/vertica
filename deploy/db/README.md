# Vertica DB Stack

Provision a Vertica Community Edition instance on an Amazon Linux 2023 EC2 host. The GitHub Actions workflow in `.github/workflows/db-apply-destroy.yml` runs automatically for commits touching `deploy/db/**`.

## Usage

1. Configure repository secrets: `AWS_REGION`, `AWS_ACCOUNT_ID`, and either (`AWS_ROLE_TO_ASSUME` + `AWS_OIDC_ROLE_SESSION_NAME`) or (`AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`). Optionally set `ALLOWED_CIDRS` to a comma-separated list like `"49.x.x.x/32","122.x.x.x/32"`.
2. Push changes under `deploy/db/` or trigger the **DB Stack (apply/destroy)** workflow manually.
3. Select `action=apply` to provision. The workflow summary prints the public IP and a ready-to-copy Vertica connect string.
4. Select `action=destroy` to tear everything down when finished.

The instance defaults to a Spot `t3.xlarge` with 50 GiB gp3 storage and exposes port 5433 only to the allowed CIDRs. Smoke tests run via AWS Systems Manager using `/usr/local/bin/db-smoke.sh`.
