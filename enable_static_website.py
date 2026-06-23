import os
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, StaticWebsite

ACCOUNT = os.environ["STORAGE_ACCOUNT_NAME"]
account_url = f"https://{ACCOUNT}.blob.core.windows.net"

cred = DefaultAzureCredential()
service = BlobServiceClient(account_url, credential=cred)

service.set_service_properties(
    static_website=StaticWebsite(
        enabled=True,
        index_document="index.html",
        error_document404_path="404.html",
    )
)
print("Static website hosting enabled.")

# Verify by reading back — catches silently-dropped parameters
props = service.get_service_properties()
sw = props.get("static_website")
assert sw.enabled is True, "static website not enabled"
assert sw.index_document == "index.html", f"unexpected index_document: {sw.index_document}"
assert sw.error_document404_path == "404.html", f"unexpected 404 path: {sw.error_document404_path}"
print(f"Verified: index={sw.index_document}, 404={sw.error_document404_path}")
