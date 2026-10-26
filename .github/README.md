# GitHub Actions setup

[`workflows/ci-deploy.yml`](workflows/ci-deploy.yml) validates changes and deploys
the development environment after changes reach `main`.

## Publish this project as the repository root

Create the GitHub repository with the **contents of `reserving-prototype` at its
root**. GitHub must find `.github/workflows/ci-deploy.yml` at the repository root,
alongside `main.py`, `requirements.txt`, `scripts/`, and `infrastructure/`.

The current local folder is inside a parent Git repository for another project.
Publish this project separately; adding a nested project folder to that parent
repository would not put this workflow in GitHub's workflow directory.

## Configure Azure authentication

1. Create or select the development resource group, normally `rg-reserving-dev`.
   The workflow deploys into an existing group.
2. Create a Microsoft Entra application with a service principal, or a
   user-assigned managed identity, for GitHub deployment.
3. Give that identity the **Contributor** role scoped to the development resource
   group. This covers the current template and application deployment. The
   template does not create role assignments.
4. Add a federated identity credential that trusts this GitHub repository and its
   **`dev` environment**. Use issuer `https://token.actions.githubusercontent.com`
   and audience `api://AzureADTokenExchange`.

Use the actual OIDC subject configured for your repository. GitHub's default
subject format for newly created repositories now includes immutable owner and
repository IDs, so do not copy an older repository-name-only subject example
without checking it. Follow [GitHub's current Azure OIDC guide](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-azure)
and [Azure's federated identity setup](https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure-openid-connect).

The workflow uses short-lived federated authentication. It does not need your
interactive Azure login or an Azure client secret.

## Configure the GitHub environment and approvals

Create **Settings > Environments > `dev`**. Add these **environment variables**;
the workflow reads them through GitHub's `vars` context:

| Variable | Value |
| --- | --- |
| `AZURE_CLIENT_ID` | Deployment identity's application/client ID. |
| `AZURE_TENANT_ID` | Azure tenant ID. |
| `AZURE_SUBSCRIPTION_ID` | Target subscription ID. |
| `AZURE_RESOURCE_GROUP` | Optional; defaults to `rg-reserving-dev`. |
| `INFRA_DEPLOYMENT_NAME` | Optional; defaults to `reserving-dev-infrastructure`. |

Keep the infrastructure deployment name stable: API-only releases use its
stored `appServiceName` and `appServiceUrl` outputs. A missing output causes the
workflow to deploy Bicep before publishing the API.

Restrict deployments for `dev` to `main`. Configure branch protection or a
ruleset for `main` to require pull requests, approving reviews, and the workflow's
**Validate** check before merging. Approval allows a merge; the merge triggers
deployment. Pull request validation does not authenticate to Azure.

If you want another approval immediately before deployment, configure required
reviewers on `dev`. Environment and reviewer availability depend on the GitHub
plan and whether the repository is public or private; see
[GitHub environment settings](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).

## What runs

| Event or change | Result |
| --- | --- |
| Pull request targeting `main` | Compile Bicep and parameter files, check PowerShell syntax, and run Python tests. No deployment. |
| Push to `main` | Validate, determine affected components, and deploy those components to `dev`. |
| Manual run on `main` | Validate and deploy selected components; choose `deploy_all` to force both infrastructure and API. |
| No successful release baseline | Deploy infrastructure and API. |
| Infrastructure inputs, except production-only parameters or Markdown | Deploy the full development Bicep entry point, then API code. |
| `main.py`, `requirements.txt`, or `scripts/deploy-api.ps1` | Deploy API code. |
| Workflow files or `scripts/get-deployment-plan.py` | Deploy infrastructure and API. |
| Documentation, tests, development test dependencies, or only `prod.bicepparam` | Validation only. |

The change planner compares the checked-out commit with the last successful
`main` push or manual run of this workflow, rather than only the previous commit.
Changes from failed releases therefore remain eligible for the next release.
Deleted and renamed files are included. When there is no usable baseline, the
workflow selects both deployments, even if the current change is documentation
only. A manual `deploy_all` run also takes precedence over path selection.

Releases to `dev` run one at a time, and a newer run does not cancel an active
deployment. A queued run whose commit is no longer the tip of `main` is rejected
before deployment. To retry a failed release, rerun it if its commit is still
current, or manually run the latest `main` revision.

After changing GitHub environment variables or making Azure changes outside this
workflow, manually run with `deploy_all` enabled. Those changes do not appear in
the repository's file diff.

After Azure deployment, the workflow checks the API's health and greeting
endpoints. Startup and build settings come from Bicep; `deploy-api.ps1` publishes
the application ZIP without rewriting those settings.

## Extend deployment selection

Change rules live in [`scripts/get-deployment-plan.py`](../scripts/get-deployment-plan.py).
Keep rules aligned with each component's deployment package and add planning
tests when adding paths or services.

The current API ZIP contains only `main.py` and `requirements.txt`. The separate
`validation/` code is not imported by this API or included in that ZIP, so it is
not currently an API deployment input. If the API starts using it, update both
the package contents and the planner's API paths in the same change.

As more applications appear, give each one a source directory, an explicit
resource-name output, and a deployment artifact. Reuse common workflow steps
for applications with the same deployment method. Let Bicep references and
module outputs order Azure resources; use workflow ordering only where one
application release requires another deployment to finish first.

Production parameters are compiled for validation, but this workflow does not
deploy production. Add a separate environment, identity, change scope, and
approval policy when production deployment is needed.
