"""Compile Bicep locally and check the SQL deployment contract without Azure calls."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest
from uuid import UUID


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def resources(template):
    result = template.get("resources", [])
    return list(result.values()) if isinstance(result, dict) else result


def resource_of_type(template, resource_type):
    matches = [resource for resource in resources(template) if resource["type"] == resource_type]
    if len(matches) != 1:
        raise AssertionError(f"Expected one {resource_type} resource, found {len(matches)}.")
    return matches[0]


class SqlInfrastructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.azure_cli = shutil.which("az")
        if cls.azure_cli is None:
            raise RuntimeError("SQL infrastructure tests require Azure CLI and Bicep. Install Azure CLI, then run az bicep install.")

        # CI installs the pinned Bicep version first. Tests do not install tools.
        cls.run_bicep("version")
        cls.main_template = cls.run_bicep("build", "--file", "infrastructure/main.bicep", "--stdout")
        sql_deployments = [
            resource
            for resource in resources(cls.main_template)
            if resource["type"] == "Microsoft.Resources/deployments"
            and any(
                child["type"] == "Microsoft.Sql/servers"
                for child in resources(resource.get("properties", {}).get("template", {}))
            )
        ]
        if len(sql_deployments) != 1:
            raise AssertionError(f"Expected one SQL module deployment, found {len(sql_deployments)}.")
        cls.sql_deployment = sql_deployments[0]
        cls.sql_template = cls.sql_deployment["properties"]["template"]
        cls.server = resource_of_type(cls.sql_template, "Microsoft.Sql/servers")
        cls.database = resource_of_type(cls.sql_template, "Microsoft.Sql/servers/databases")
        cls.environment_parameters = {}
        for environment in ("dev", "prod"):
            compiled = cls.run_bicep(
                "build-params", "--file", f"infrastructure/parameters/{environment}.bicepparam", "--stdout",
            )
            cls.environment_parameters[environment] = json.loads(compiled["parametersJson"])["parameters"]

    @classmethod
    def run_bicep(cls, *arguments):
        result = subprocess.run(
            [cls.azure_cli, "bicep", *arguments, "--only-show-errors"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8-sig", timeout=120,
        )
        if result.returncode:
            raise RuntimeError(f"Bicep {' '.join(arguments)} failed. Check that Bicep is installed.\n{result.stderr}")
        if arguments[0] == "version":
            return result.stdout
        return json.loads(result.stdout)

    def test_sql_is_opt_in_and_enabled_only_for_development(self):
        self.assertIs(self.main_template["parameters"]["sqlEnabled"]["defaultValue"], False)
        self.assertEqual(self.sql_deployment["condition"], "[parameters('sqlEnabled')]")
        self.assertIs(self.environment_parameters["dev"]["sqlEnabled"]["value"], True)
        self.assertIs(self.environment_parameters["prod"]["sqlEnabled"]["value"], False)

    def test_administrator_is_an_explicit_environment_input(self):
        main_parameters = self.main_template["parameters"]
        self.assertEqual(main_parameters["sqlAdministratorLogin"]["defaultValue"], "")
        self.assertEqual(main_parameters["sqlAdministratorObjectId"]["defaultValue"], "")
        self.assertEqual(set(main_parameters["sqlAdministratorPrincipalType"]["allowedValues"]), {"User", "Group"})
        module_parameters = self.sql_deployment["properties"]["parameters"]
        for module_name, main_name in {
            "administratorLogin": "sqlAdministratorLogin",
            "administratorObjectId": "sqlAdministratorObjectId",
            "administratorPrincipalType": "sqlAdministratorPrincipalType",
        }.items():
            with self.subTest(parameter=module_name):
                self.assertEqual(module_parameters[module_name]["value"], f"[parameters('{main_name}')]")
        dev = self.environment_parameters["dev"]
        self.assertTrue(dev["sqlAdministratorLogin"]["value"].strip())
        self.assertEqual(str(UUID(dev["sqlAdministratorObjectId"]["value"])), dev["sqlAdministratorObjectId"]["value"])
        self.assertEqual(dev["sqlAdministratorPrincipalType"]["value"], "User")

    def test_module_uses_shared_naming_location_tags_and_database_name(self):
        parameters = self.sql_deployment["properties"]["parameters"]
        for name, expression in {
            "namePrefix": "[variables('namePrefix')]",
            "location": "[parameters('location')]",
            "tags": "[variables('commonTags')]",
            "databaseName": "[parameters('sqlDatabaseName')]",
        }.items():
            with self.subTest(parameter=name):
                self.assertEqual(parameters[name]["value"], expression)
        self.assertEqual(self.server["location"], "[parameters('location')]")
        self.assertEqual(self.database["location"], "[parameters('location')]")
        self.assertEqual(self.server["tags"], "[parameters('tags')]")
        self.assertEqual(self.database["tags"], "[parameters('tags')]")

    def test_server_requires_entra_authentication_without_sql_credentials(self):
        properties = self.server["properties"]
        administrator = properties["administrators"]
        self.assertEqual(administrator["administratorType"], "ActiveDirectory")
        self.assertIs(administrator["azureADOnlyAuthentication"], True)
        self.assertEqual(administrator["login"], "[parameters('administratorLogin')]")
        self.assertEqual(administrator["sid"], "[parameters('administratorObjectId')]")
        self.assertEqual(administrator["principalType"], "[parameters('administratorPrincipalType')]")
        self.assertEqual(administrator["tenantId"], "[tenant().tenantId]")
        self.assertNotIn("administratorLogin", properties)
        self.assertNotIn("administratorLoginPassword", properties)
        self.assertFalse(any("password" in name.lower() for name in self.sql_template["parameters"]))

    def test_network_access_is_closed_and_tls_is_required(self):
        properties = self.server["properties"]
        self.assertEqual(properties["publicNetworkAccess"], "Disabled")
        self.assertEqual(properties["minimalTlsVersion"], "1.2")
        self.assertFalse(any(resource["type"].endswith("/firewallRules") for resource in resources(self.sql_template)))

    def test_database_is_deployed_under_its_logical_server(self):
        server_name_expression = self.server["name"][1:-1]
        self.assertIn(server_name_expression, self.database["name"])
        self.assertIn("parameters('databaseName')", self.database["name"])
        dependencies = self.database.get("dependsOn", [])
        self.assertTrue(any("Microsoft.Sql/servers" in dependency and server_name_expression in dependency for dependency in dependencies))

    def test_free_offer_pauses_instead_of_continuing_with_charges(self):
        for name, expected in {"name": "GP_S_Gen5", "tier": "GeneralPurpose", "family": "Gen5", "capacity": 2}.items():
            with self.subTest(sku=name):
                self.assertEqual(self.database["sku"][name], expected)
        properties = self.database["properties"]
        self.assertIs(properties["useFreeLimit"], True)
        self.assertEqual(properties["freeLimitExhaustionBehavior"], "AutoPause")
        self.assertEqual(properties["maxSizeBytes"], 32 * 1024 ** 3)
        self.assertIs(properties["zoneRedundant"], False)
        self.assertEqual(properties["readScale"], "Disabled")

    def test_backups_are_local_with_seven_day_point_in_time_retention(self):
        self.assertEqual(self.database["properties"]["requestedBackupStorageRedundancy"], "Local")
        retention = resource_of_type(self.sql_template, "Microsoft.Sql/servers/databases/backupShortTermRetentionPolicies")
        self.assertIn("'default'", retention["name"])
        self.assertEqual(retention["properties"]["retentionDays"], 7)
        self.assertTrue(any("Microsoft.Sql/servers/databases" in dependency for dependency in retention.get("dependsOn", [])))

    def test_module_outputs_expose_resource_identifiers_without_credentials(self):
        outputs = self.sql_template["outputs"]
        self.assertTrue({"serverName", "serverResourceId", "serverFqdn", "databaseName", "databaseResourceId"}.issubset(outputs))
        self.assertIn("Microsoft.Sql/servers", outputs["serverResourceId"]["value"])
        self.assertIn("Microsoft.Sql/servers/databases", outputs["databaseResourceId"]["value"])
        self.assertIn("fullyQualifiedDomainName", outputs["serverFqdn"]["value"])
        self.assertEqual(outputs["databaseName"]["value"], "[parameters('databaseName')]")
        self.assertFalse(any("password" in name.lower() or "connectionstring" in name.lower() for name in outputs))

    def test_main_forwards_sql_outputs_only_when_enabled(self):
        for main_name, module_name in {
            "sqlServerName": "serverName",
            "sqlServerResourceId": "serverResourceId",
            "sqlServerFqdn": "serverFqdn",
            "sqlDatabaseName": "databaseName",
            "sqlDatabaseResourceId": "databaseResourceId",
        }.items():
            with self.subTest(output=main_name):
                output = self.main_template["outputs"][main_name]
                self.assertEqual(output["type"], "string")
                self.assertTrue(output["value"].startswith("[if(parameters('sqlEnabled'), "))
                self.assertIn(f".outputs.{module_name}.value", output["value"])
                self.assertTrue(output["value"].endswith(", '')]"))


if __name__ == "__main__":
    unittest.main()
