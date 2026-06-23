import os
from azure.identity import DefaultAzureCredential
from azure.mgmt.resource import ResourceManagementClient

cred = DefaultAzureCredential()
client = ResourceManagementClient(cred, os.environ["AZURE_SUBSCRIPTION_ID"])
RG = os.environ["AZURE_RG"]

if client.resource_groups.check_existence(RG):
    print(f"Deleting resource group '{RG}'...")
    client.resource_groups.begin_delete(RG).result()
    print("Deleted.")
else:
    print(f"Resource group '{RG}' does not exist — nothing to do.")
