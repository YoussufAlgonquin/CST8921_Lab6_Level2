# CST8921 Lab 6 – Code-First Static Site on Azure

## Prerequisites

```bash
az login
az account set --subscription "<YOUR_SUBSCRIPTION_ID>"
python -m venv .venv && source .venv/bin/activate
pip install azure-identity azure-mgmt-resource azure-mgmt-storage \
            azure-storage-blob azure-data-tables azure-functions
```

## Environment variables

```bash
export AZURE_SUBSCRIPTION_ID="98fe3316-7082-4299-bd73-cc87fb355015"
export STORAGE_ACCOUNT_NAME="cst8921lab6yh01"
export AZURE_RG="cst8921-lab6-rg"
export AZURE_LOCATION="canadacentral"
```

## Run order

```
1.  python provision.py                          # Part B – create RG + storage account
2.  az role assignment create  ...               # Part A – grant data-plane role (see below)
3.  python enable_static_website.py              # Part C – enable $web hosting
4.  python deploy.py                             # Part E – upload site assets
5.  cd api && func start                         # Part F – run Function locally
       # In another terminal: open http://localhost:7071/api/visits
6.  func azure functionapp publish cst8921lab6fn # Part F – deploy to Azure (after creating FA)
       # Then update site/config.js with the live Function URL and re-run deploy.py
7.  az afd profile create ...                    # Part G – Front Door setup (see lab doc)
8.  python cleanup.py                            # Part H – teardown when done
```

### Data-plane role assignment (run after step 1)

```bash
az role assignment create \
  --assignee "$(az ad signed-in-user show --query id -o tsv)" \
  --role "Storage Blob Data Owner" \
  --scope "/subscriptions/$AZURE_SUBSCRIPTION_ID/resourceGroups/$AZURE_RG/providers/Microsoft.Storage/storageAccounts/$STORAGE_ACCOUNT_NAME"
```

## Files

| File | Purpose |
|---|---|
| `provision.py` | Part B – management-plane: create RG + storage account |
| `enable_static_website.py` | Part C – data-plane: enable static website hosting |
| `deploy.py` | Part E – data-plane: upload site/ assets with content-type + cache headers |
| `cleanup.py` | Part H – management-plane: delete entire resource group |
| `site/` | Static front end (index.html, config.js, 404.html) |
| `api/` | Azure Functions app (Python v2) – visit counter backed by Table Storage |
