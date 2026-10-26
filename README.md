# Reserving prototype

A small FastAPI service hosted on Azure App Service. The API currently exposes
simple GET endpoints so you can verify local development and cloud deployment.

## Run locally

With [uv](https://docs.astral.sh/uv/) installed, run these commands from the
repository root in PowerShell:

```powershell
uv venv --python 3.12
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

The API listens at `http://127.0.0.1:8000`. Open
`http://127.0.0.1:8000/docs` for interactive API documentation. Stop the local
server with **Ctrl+C**.

## Test with Postman

Create a Postman variable named `baseUrl` with the value
`http://127.0.0.1:8000`. Send a **GET** request to:

```text
{{baseUrl}}/hello?name=Jane
```

Use **No Auth** and no request body. A successful request returns HTTP `200`:

```json
{
  "message": "Hello, Jane!"
}
```

| GET path | Response |
| --- | --- |
| `/` | `{"message":"Reserving API is running."}` |
| `/hello` | `{"message":"Hello, World!"}` |
| `/hello?name=Jane` | `{"message":"Hello, Jane!"}` |
| `/health` | `{"status":"ok"}` |
| `/docs` | Interactive API documentation in a browser. |

The optional `name` query parameter accepts 1 to 100 characters. Invalid values
return HTTP `422` with validation details.

## Run checks

Install the development dependencies and run the API and deployment-planning
tests from the repository root:

```powershell
uv pip install --python .venv/Scripts/python.exe -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The Bicep compilation commands are in [the infrastructure guide](infrastructure/README.md#check-locally).

## Deploy to Azure

Install Azure CLI and sign in with `az login`. Select your intended subscription
with `az account set --subscription <id-or-name>`.

If the development resource group does not exist, create it:

```powershell
az group create --name rg-reserving-dev --location uksouth
```

Preview the App Service infrastructure:

```powershell
az deployment group what-if --resource-group rg-reserving-dev --parameters infrastructure/parameters/dev.bicepparam
```

`what-if` only previews changes. The `create` command provisions the Linux B1
plan and Python web app; the plan incurs Azure charges while it exists. The
resource group's location determines the resources' region.

Create or update the infrastructure and deploy the API in one line:

```powershell
$appName = az deployment group create --resource-group rg-reserving-dev --parameters infrastructure/parameters/dev.bicepparam --query properties.outputs.appServiceName.value --output tsv; if ($LASTEXITCODE -eq 0 -and $appName) { .\scripts\deploy-api.ps1 -ResourceGroupName rg-reserving-dev -AppName $appName }
```

Bicep returns the deployed web app's name as `appServiceName`. The command passes
that name to the API deployment, so it targets the app from this deployment even
when the resource group contains multiple web apps. API deployment runs only
when infrastructure deployment succeeds and returns a name.

For API-only updates, you can run:

```powershell
.\scripts\deploy-api.ps1
```

Without `-AppName`, the script requires exactly one web app in `rg-reserving-dev`.
It deploys a ZIP containing `main.py` and `requirements.txt` to the selected app
and prints the app URL when deployment succeeds. Bicep owns the startup command
and remote build settings; apply infrastructure changes before publishing code
that needs different hosting settings.
Run the script again after changing the API to publish an update.

The upload is submitted asynchronously, and Azure CLI waits for the deployment
result before the script reports success. The first deployment can take several
minutes while Azure prepares Python and installs dependencies.

For a different resource group or a group containing multiple web apps, specify
the target explicitly:

```powershell
.\scripts\deploy-api.ps1 -ResourceGroupName 'your-resource-group' -AppName 'your-app-name'
```

To test the cloud app in Postman, replace `baseUrl` with the HTTPS URL printed by
the script, then send the same GET request to `{{baseUrl}}/hello?name=Jane`.
Open that base URL followed by `/docs` in a browser for interactive documentation.

## GitHub Actions

[The CI and deployment workflow](.github/workflows/ci-deploy.yml) validates pull
requests to `main`. After a merge to `main`, it deploys development infrastructure
and API code according to the changed files. Infrastructure changes deploy first
and also publish the API so new hosting resources receive application code.
API-only changes reuse the named infrastructure deployment's outputs.

The workflow uses Azure OIDC authentication and the GitHub environment `dev`.
Complete [the repository and Azure setup](.github/README.md) before running it.
That guide also covers approvals, manual deployments, and extending the change
rules when more services are added. Production deployment is not configured.

See [the infrastructure guide](infrastructure/README.md) for Bicep parameters and
the remaining service modules.
