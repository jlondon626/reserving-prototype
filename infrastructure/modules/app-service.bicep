targetScope = 'resourceGroup'

@description('Shared resource name prefix using letters, digits and hyphens. Leaves room for the web app name suffix.')
@minLength(1)
@maxLength(39)
param namePrefix string

@description('Azure region for the plan and web app.')
param location string = resourceGroup().location

@description('Tags applied to both the plan and web app.')
param tags object = {}

@description('Dedicated Linux App Service SKU, Basic or higher, supporting Always On.')
param skuName string = 'B1'

@description('Python minor version available in App Service, for example 3.12.')
param pythonVersion string = '3.12'

@description('Optional startup command. Empty uses platform detection; set this when the application entry point requires it.')
param startupCommand string = ''

@description('Build Python source and install dependencies during deployment. Disable when deploying compatible prebuilt artifacts.')
param buildDuringDeployment bool = true

@description('Additional app settings, such as monitoring and database endpoints. Use Key Vault references for credentials. Build flags are controlled by buildDuringDeployment.')
@secure()
param additionalAppSettings object = {}

// Keep the global web app name stable across deployments to this resource group.
var webAppName = '${namePrefix}-webapp-${uniqueString(resourceGroup().id, namePrefix)}'

// Python source deployments use Oryx build automation
var appSettings = union(additionalAppSettings, {
  SCM_DO_BUILD_DURING_DEPLOYMENT: buildDuringDeployment ? 'true' : 'false'
  ENABLE_ORYX_BUILD: buildDuringDeployment ? 'true' : 'false'
})

resource appServicePlan 'Microsoft.Web/serverfarms@2025-03-01' = {
  name: '${namePrefix}-plan'
  location: location
  tags: tags
  kind: 'linux'
  sku: {
    name: skuName
    capacity: 1
  }
  properties: {
    reserved: true
  }
}

resource appService 'Microsoft.Web/sites@2025-03-01' = {
  name: webAppName
  location: location
  tags: tags
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    publicNetworkAccess: 'Enabled'
    siteConfig: {
      linuxFxVersion: 'PYTHON|${pythonVersion}'
      appCommandLine: startupCommand
      alwaysOn: true
      minTlsVersion: '1.2'
      scmMinTlsVersion: '1.2'
      ftpsState: 'Disabled'
      appSettings: [for setting in items(appSettings): {
        name: setting.key
        value: string(setting.value)
      }]
    }
  }
}

@description('Resource ID of the Linux App Service plan.')
output planResourceId string = appServicePlan.id

@description('Resource ID of the web app.')
output appResourceId string = appService.id

@description('Name of the web app for application code deployment.')
output appName string = appService.name

@description('HTTPS URL returned by the web app resource.')
output appUrl string = 'https://${appService.properties.defaultHostName}'

@description('System-assigned managed identity principal ID. Downstream services must grant it access separately.')
output principalId string = appService.identity.principalId
