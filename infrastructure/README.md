# Azure infrastructure

Bicep infrastructure for the reserving prototype. The entry point targets an
existing resource group and provisions a dedicated Linux App Service plan and
Python web app. Development parameters also enable an Azure SQL logical server
and database. The remaining service modules and their calls are placeholders.
Application code deployment is a separate step.

## Structure

```text
infrastructure/
|-- main.bicep
|-- bicepconfig.json
|-- parameters/
|   |-- dev.bicepparam
|   `-- prod.bicepparam
|-- modules/
|   |-- app-service.bicep
|   |-- sql.bicep
|   |-- cosmos-db.bicep
|   |-- api-management.bicep
|   `-- monitoring.bicep
`-- README.md
```

- `main.bicep` owns shared naming, location, tags and module wiring.
- `parameters/` supplies environment-specific settings to the same entry point.
- `modules/` groups related resources by service. App Service and SQL are implemented;
  the other stubs document their intended resources, inputs and outputs.
- `bicepconfig.json` enables the standard Bicep linter.

Location defaults to the target resource group's location. Each service will adapt
the shared name prefix to its own naming rules and uniqueness requirements.

## App Service

The module accepts the shared `namePrefix`, location and tags from `main.bicep`.
It creates a Linux plan with one instance and a web app with a system-assigned
managed identity, HTTPS-only access, TLS 1.2 minimum and FTP disabled. Public
network access is enabled; VNet integration and private endpoints are not yet
implemented. The web app name includes a deterministic suffix derived from the
resource group and prefix to reduce global name collisions.

The entry point exposes the following environment settings:

| Parameter | Default | Purpose |
| --- | --- | --- |
| `appServiceSkuName` | `B1` | Dedicated plan size; Basic or higher is required for Always On. |
| `appServicePythonVersion` | `3.12` | Python minor version in the built-in Linux runtime. |
| `appServiceStartupCommand` | `python -m uvicorn main:app --host 0.0.0.0 --port 8000` | Start the FastAPI app from the deployed `main.py`. |
| `appServiceBuildDuringDeployment` | `true` | Build Python source during deployment. |
| `appServiceAppSettings` | Empty object | Additional environment variables, such as database and monitoring endpoints. |

Both parameter files currently use B1 and Python 3.12 as initial settings.
Production capacity still needs choosing for the actual workload. Confirm runtime
availability before deployment with `az webapp list-runtimes --os linux`.

App settings are environment variables; some configure the hosting platform while
others configure application code. This module sets:

- `SCM_DO_BUILD_DURING_DEPLOYMENT=true` to build deployed source and install dependencies.
- `ENABLE_ORYX_BUILD=true` to use the Oryx build engine on Linux.

Setting `appServiceBuildDuringDeployment=false` sets both flags to `false` for
compatible prebuilt deployment artifacts. The flags take precedence over values
in `appServiceAppSettings`. `WEBSITE_RUN_FROM_PACKAGE` is deliberately absent:
running directly from a mounted ZIP is not supported by Python App Service apps.
Source ZIP deployment with build automation is supported.

The API entry point is the repository-root `main.py`, and `requirements.txt`
declares FastAPI and Uvicorn. Both files are placed at the deployment ZIP's root
so Oryx can install dependencies. The default startup command runs Uvicorn on
port 8000, listening on all container interfaces. Change
`appServiceStartupCommand` if the application's module or callable changes.

The API does not consume SQL settings yet. A later change can pass the SQL
module's `serverFqdn` and `databaseName` outputs into application settings
when SQL is enabled. Connectivity also requires suitable network access, an
identity-aware driver, and separate database permissions for the web app's
identity. The monitoring module remains a placeholder and will need
instrumentation in addition to a connection string.

The entry point returns `appServiceName`, `appServiceUrl`, `appServiceResourceId`
and `appServicePrincipalId` for downstream configuration. Pass `appServiceName`
to the API deployment script to target the app created or updated by Bicep.

## Azure SQL

`modules/sql.bicep` defines a logical server, one database, and its short-term
backup retention policy. The database references its parent server, so Bicep
orders their deployment automatically. Server naming uses the shared prefix and
a deterministic suffix derived from the resource group; the database defaults
to `<appName>-<environmentName>`.

SQL is opt-in through these entry-point parameters:

| Parameter | Default | Purpose |
| --- | --- | --- |
| `sqlEnabled` | `false` | Provision the SQL module for this environment. |
| `sqlAdministratorLogin` | Empty | Friendly name of the Microsoft Entra SQL administrator; required when SQL is enabled. |
| `sqlAdministratorObjectId` | Empty | That administrator's tenant-specific Entra object ID; required when SQL is enabled. |
| `sqlAdministratorPrincipalType` | `User` | Whether the administrator is a `User` or `Group`. |
| `sqlDatabaseName` | `<appName>-<environmentName>` | Database name within the logical server. |

`dev.bicepparam` enables SQL with the Entra user selected during setup as the
administrator.
The administrator name and object ID identify that user; they are not passwords.
The server enables Entra-only authentication and TLS 1.2 minimum. The GitHub
deployment identity can provision the resources through Azure RBAC, but is not
automatically a SQL database user or administrator.

The database is configured for the development free offer:

- General Purpose serverless Gen5, with a maximum capacity of 2 vCores.
- Maximum data size of 32 GiB, local backup redundancy, and seven-day
  point-in-time restore retention.
- `useFreeLimit=true` and `freeLimitExhaustionBehavior=AutoPause`, so it pauses
  when the monthly free allowance is exhausted rather than enabling overage billing.
- Platform defaults for minimum capacity and idle auto-pause, without overriding
  the free offer's idle policy.

Review eligibility and current limits in [Microsoft's free-tier guide](https://learn.microsoft.com/en-us/azure/azure-sql/database/free-tier).
This is a development configuration. SQL remains disabled in
`prod.bicepparam` until its authentication and capacity design is chosen.

This first step creates SQL infrastructure only. Public network access is
disabled, and there are no firewall rules or private endpoints. Neither a
developer's computer nor the App Service can connect yet. Network access,
database users for the app identity, an application driver, tables, and schema
migrations belong to the next integration step.

The main entry point exposes `sqlServerName`, `sqlServerResourceId`,
`sqlServerFqdn`, `sqlDatabaseName`, and `sqlDatabaseResourceId`. They are empty
strings when SQL is disabled. The module returns its database name as
`databaseName`.

Setting `sqlEnabled=false` does not delete SQL resources that already exist.
The deployment uses incremental mode; retiring a database remains a separate,
explicit operation.

## Implementing a service

1. Define its resources in the corresponding module and uncomment the shared
   parameters as they become used.
2. Add inputs for service-specific settings and expose actual resource IDs,
   endpoints or managed identity principal IDs as outputs.
3. Uncomment its module call in `main.bicep` and pass any additional inputs.
4. Pass outputs between modules to establish dependencies; for example, pass the
   monitoring connection string to the app module.
5. Add settings that vary by environment to `dev.bicepparam` and
   `prod.bicepparam`, keeping the resource definitions shared.

Keep secret values out of parameter files and ordinary outputs. Prefer managed
identities where supported; use secure parameters and Key Vault when secrets are
required. The service modules are starting points, not a requirement to deploy
every listed service.

## Check locally

Run these commands from the repository root with the standalone Bicep CLI:

```powershell
bicep build infrastructure/main.bicep --stdout
bicep build-params infrastructure/parameters/dev.bicepparam --stdout
bicep build-params infrastructure/parameters/prod.bicepparam --stdout
```

These commands compile and lint locally without deploying. With Azure CLI, use
the corresponding commands with `--file`:

```powershell
az bicep build --file infrastructure/main.bicep --stdout
az bicep build-params --file infrastructure/parameters/dev.bicepparam --stdout
az bicep build-params --file infrastructure/parameters/prod.bicepparam --stdout
```

Check module files individually with `bicep build` while their calls in
`main.bicep` are still commented out.

`tests/test_sql_infrastructure.py` uses the real Bicep compiler to inspect the
generated SQL resource definitions, parent dependencies, authentication,
network boundary, free-offer policy, backup retention, outputs, and development
versus production configuration. These are compiled infrastructure contract
tests: no Azure login, deployment, or SQL connection is required. Install Azure
CLI and Bicep before running the Python suite described in
[the project README](../README.md#run-checks).

Compilation and contract tests do not prove Azure provider acceptance or SQL
connectivity. Use `what-if` to check the planned deployment against Azure;
connection checks will follow when database access is implemented.

## Preview and deploy

Install Azure CLI, sign in with `az login` and
select the intended subscription with `az account set --subscription <id>`.
The target resource group must already exist. If it does not, create it in the
intended region first:

```powershell
az group create --name rg-reserving-dev --location uksouth
```

Replace the example resource group name below with your development resource group.
Run from the repository root:

```powershell
$resourceGroupName = 'rg-reserving-dev'
az deployment group what-if --resource-group $resourceGroupName --parameters infrastructure/parameters/dev.bicepparam
```

`what-if` only previews changes; it does not create resources. Review the
preview before running the deployment command. This creates or updates the B1
plan, web app, and SQL resources enabled in the development parameters. The plan
incurs Azure charges while it exists; the SQL free offer is configured to pause
at its free limit:

```powershell
$appName = az deployment group create --resource-group $resourceGroupName --parameters infrastructure/parameters/dev.bicepparam --query properties.outputs.appServiceName.value --output tsv
if ($LASTEXITCODE -ne 0 -or -not $appName) { throw 'Infrastructure deployment failed or returned no app name.' }
```

After the infrastructure deployment succeeds, publish the API source:

```powershell
.\scripts\deploy-api.ps1 -ResourceGroupName $resourceGroupName -AppName $appName
```

The deployment output supplies the web app name, so this flow works even when
the resource group contains multiple web apps. Bicep owns the FastAPI startup
command and Oryx build flags. The API script deploys `.artifacts/reserving-api.zip`
containing `main.py` and `requirements.txt` at its root. For API-only updates,
provide `-AppName 'your-app-name'` explicitly, or omit it when the resource group
contains exactly one web app. The script prints the deployed URL for Postman or
a browser. See [the project README](../README.md) for a combined one-line deploy
command, local development and sample requests.

The script uses an asynchronous upload to avoid holding a single upload request
open during the build. Azure CLI waits for completion, and the script checks the
returned deployment status before reporting success.

## GitHub deployment

[The GitHub Actions workflow](../.github/workflows/ci-deploy.yml) compiles Bicep
and both environment parameter files before running the Python tests, including
the SQL infrastructure contracts. Deployment targets
development only, using `dev.bicepparam` and a named infrastructure deployment
that defaults to `reserving-dev-infrastructure`.

Infrastructure changes deploy the full entry point before the API. The workflow
passes `appServiceName` from that deployment into the API script. For API-only
changes, it reads the existing named deployment's outputs. If those outputs are
missing, it reapplies Bicep before publishing the API. It never selects an app by
counting the web apps in the resource group.

The resource group and Azure federated identity must already exist. Follow
[the workflow setup guide](../.github/README.md) for the GitHub `dev` environment,
Azure permissions, and change-selection rules. The deployment identity needs
permission to update the resources defined here; if future modules create role
assignments, review its permissions as part of that change.

SQL module and development SQL parameter changes are infrastructure inputs, so
the existing planner deploys Bicep before publishing the API. No new SQL-specific
deployment script is needed. SQL connection checks are not part of the API
health endpoint at this stage.

Use `prod.bicepparam` with the intended production resource group for production.
If resource group creation becomes part of this repository, add a
subscription-scoped wrapper that creates the group and calls `main.bicep`.

References: [Bicep modules](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/modules),
[parameter files](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/parameter-files),
[Python app configuration](https://learn.microsoft.com/en-us/azure/app-service/configure-language-python),
[custom Python startup commands](https://learn.microsoft.com/en-us/azure/developer/python/configure-python-web-app-on-app-service),
[ZIP deployment](https://learn.microsoft.com/en-us/azure/app-service/deploy-zip),
[run-from-package limitations](https://learn.microsoft.com/en-us/azure/app-service/deploy-run-package),
[Oryx build settings](https://github.com/microsoft/Oryx/blob/main/doc/hosts/appservice.md),
[SQL server resource reference](https://learn.microsoft.com/en-us/azure/templates/microsoft.sql/2025-01-01/servers),
[SQL database resource reference](https://learn.microsoft.com/en-us/azure/templates/microsoft.sql/2025-01-01/servers/databases),
[tool installation](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/install).
