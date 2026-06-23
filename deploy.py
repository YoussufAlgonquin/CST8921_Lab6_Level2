import os
import mimetypes
import pathlib
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

ACCOUNT = os.environ["STORAGE_ACCOUNT_NAME"]
SITE_DIR = pathlib.Path("site")
CONTAINER = "$web"

account_url = f"https://{ACCOUNT}.blob.core.windows.net"
cred = DefaultAzureCredential()
container = BlobServiceClient(account_url, credential=cred).get_container_client(CONTAINER)


def cache_control_for(path: pathlib.Path) -> str:
    if path.suffix == ".html":
        return "no-cache"
    return "public, max-age=31536000, immutable"


for path in SITE_DIR.rglob("*"):
    if not path.is_file():
        continue
    blob_name = path.relative_to(SITE_DIR).as_posix()
    content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    with path.open("rb") as fh:
        container.upload_blob(
            name=blob_name,
            data=fh,
            overwrite=True,
            content_settings=ContentSettings(
                content_type=content_type,
                cache_control=cache_control_for(path),
            ),
        )
    print(f"uploaded {blob_name:<20} type={content_type:<24} cache={cache_control_for(path)}")

from azure.mgmt.storage import StorageManagementClient
mgmt = StorageManagementClient(cred, os.environ["AZURE_SUBSCRIPTION_ID"])
acct = mgmt.storage_accounts.get_properties(os.environ["AZURE_RG"], ACCOUNT)
print(f"\nVisit: {acct.primary_endpoints.web}")
