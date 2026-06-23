# CST8921 Lab 6 – Code-First Static Web Delivery on Azure
**Student:** Youssuf Hichri  
**Date:** 2026-06-22  
**Subscription:** Azure for Students (`98fe3316-7082-4299-bd73-cc87fb355015`)

---

## Objective (in my own words)

The goal of this lab is to replace the point-and-click portal workflow of the introductory static-hosting lab with a fully automated, code-driven deployment. Rather than toggling settings in the Azure portal and dragging files into a browser extension, every step is performed via the Azure SDK for Python. On top of that, the "static" site is extended with a real dynamic component: a visit counter served by an Azure Function, with the two sides connected over CORS. The result is the Jamstack architecture deployed entirely from code and delivered through Azure Front Door at the edge.

---

## Architecture Diagram

```
                    ┌─────────────────────────────┐
   Browser  ──────► │   Azure Front Door (edge)    │  HTTPS, global cache
                    └──────────────┬──────────────┘
                                   │ origin = $web primary endpoint
                                   ▼
                    ┌─────────────────────────────┐
                    │  Storage Account ($web)      │  index.html, 404.html, config.js
                    │  cst8921lab6yh01             │  Static website hosting enabled
                    │  z9.web.core.windows.net     │
                    └─────────────────────────────┘
                                   ▲
              fetch() over CORS    │
                    ┌──────────────┴──────────────┐
                    │  Azure Function (HTTP)       │  /api/visits  → Table Storage counter
                    │  cst8921lab6fn               │
                    └─────────────────────────────┘
```

The static shell (HTML, JS) is served from the storage `$web` endpoint and cached at the edge. Dynamic data (visit count) is fetched at runtime by the browser from the Azure Function, which reads/writes an Azure Table Storage entity.

---

## Part A – Authentication and the Control-Plane / Data-Plane Split

`DefaultAzureCredential` walks an ordered chain: environment variables → workload/managed identity → Azure CLI session. In this lab it falls through to the `az login` session, so the same credential object is used by every script without storing any secrets.

**Why enabling static website hosting requires a data-plane role even though it feels like a "settings" operation:**

Static website hosting is configured by calling `set_service_properties()` on the Blob Service, this is a write operation against the blob service's own configuration data, not against the ARM (Azure Resource Manager) metadata for the storage account resource. ARM (the control plane) only knows about the *existence* of the storage account. The actual blob service properties live in the blob service's data layer, accessed via the `https://<account>.blob.core.windows.net/` endpoint. Any operation that touches that endpoint requires a **data-plane** role such as `Storage Blob Data Owner`. This is why a user with `Contributor` (full control plane access) still gets `403 AuthorizationPermissionMismatch` when they try to call `set_service_properties` with `DefaultAzureCredential`: they can create and delete the account, but they cannot read or write the data inside it without an explicit data-plane role assignment.

---

## Part B – Provision Infrastructure (`provision.py`)

**LRO / poller:** `begin_create(...)` returns immediately with a **poller**: an object that wraps an ongoing long-running operation (LRO). Storage account creation can take tens of seconds; if the SDK blocked the calling thread for that entire duration it would make scripts unresponsive and impossible to run in async contexts. The LRO pattern lets the caller choose whether to block (`.result()`), poll manually, or integrate with async frameworks. In this lab we call `.result()` for simplicity, but a production script could parallelize multiple account creations.

**Security benefit of `allow_blob_public_access=False`:** The static website `$web` endpoint serves content through a special routing layer that does *not* expose raw blobs at `<account>.blob.core.windows.net/<container>/<blob>`. Setting `allow_blob_public_access=False` prevents any blob container from ever being given the `Blob` or `Container` ACL level, so no blob can be directly downloaded via the blob endpoint by an unauthenticated caller. The only public surface is the web endpoint, which serves exactly what `$web` contains. This eliminates the risk of accidentally making a sensitive container public.

**Observed output:**
```
Resource group 'cst8921-lab6-rg' ready in canadacentral.
Creating storage account 'cst8921lab6yh01' (this is a long-running operation)...
Created: cst8921lab6yh01
Primary web endpoint: https://cst8921lab6yh01.z9.web.core.windows.net/
```

---

## Part C – Enable Static Website Hosting (`enable_static_website.py`)

**The `error_document404_path` gotcha:**

The correct keyword argument is `error_document404_path` (no underscore between `document` and `404`). If you write the "natural" `error_document_404_path`, the SDK silently accepts it as an unknown keyword argument and ignores it, no exception is raised, no warning is printed, and the 404 page is never wired up.

**How to detect a silently-dropped parameter:** Read back the service properties immediately after setting them and assert on what you actually set:

```python
props = service.get_service_properties()
sw = props.get("static_website")
assert sw.error_document404_path == "404.html", f"unexpected 404 path: {sw.error_document404_path}"
```

If the property was silently dropped, the assertion fires with a clear message identifying exactly which field was missed. This pattern generalises: any time you call a "set" API, follow it with a "get" and assert.

**Observed output:**
```
Static website hosting enabled.
Verified: index=index.html, 404=404.html
```

---

## Part D – Site Files

Three files were created in `site/`:

- `index.html` - page shell with a visit counter `<span>` that is populated by a `fetch()` to `window.API_BASE/api/visits`
- `config.js` - separates the API base URL from markup so it can be updated without touching HTML. Production value: `https://cst8921lab6fn.azurewebsites.net`
- `404.html` - minimal not-found page linked back to `/`

The separation of `config.js` follows the twelve-factor principle of externalising config from code. Changing the Function URL only requires redeploying one small JS file, not regenerating all markup.

---

## Part E – Deploy with the Blob SDK (`deploy.py`)

### Content-type experiment

When `content_settings` is omitted, the SDK defaults every blob to `Content-Type: application/octet-stream`. The browser sees this type on `index.html` and offers a **file download** instead of rendering the page, the request appears in DevTools as a 200 but with a download prompt, never rendering HTML.

Restoring `ContentSettings(content_type="text/html")` causes the browser to render the page normally.

### Cache-Control strategy

| File | Cache-Control | Reason |
|---|---|---|
| `index.html`, `404.html` | `no-cache` | The browser must revalidate the HTML on every navigation. This ensures users always get a fresh entry point that references the correct asset versions. |
| `config.js` (and all other non-HTML assets) | `public, max-age=31536000, immutable` | Assets whose content never changes (because they would be renamed/fingerprinted on each release) can be cached indefinitely. `immutable` tells the browser not to revalidate even on reload during the max-age window. |

**Deployment scenario where this can break (Analysis Q3):** If `index.html` references `app.js` by a fixed name (`<script src="app.js">`), a user who cached `app.js` for one year while getting a new `index.html` could be served an old `app.js` that is API-incompatible with the new HTML, a broken page. The fix is **asset fingerprinting**: rename each asset to include a content hash (e.g., `app.abc123.js`) and update the reference in HTML on each deploy. The new hash means the browser has never cached it, so it fetches the new file.

**Observed output:**
```
uploaded index.html           type=text/html                cache=no-cache
uploaded 404.html             type=text/html                cache=no-cache
uploaded config.js            type=text/javascript          cache=public, max-age=31536000, immutable

Visit: https://cst8921lab6yh01.z9.web.core.windows.net/
```

![Screenshot 1](screenshot1.png)

---

## Part F – Serverless API (`api/function_app.py`)

The Function is a Python v2 programming model HTTP trigger at `/api/visits`. On each GET it:
1. Connects to Table Storage via the `AzureWebJobsStorage` connection string.
2. Tries to get the counter entity; if it exists, increments and updates it.
3. If the entity doesn't exist, creates it at `count = 1`.
4. Returns `{"count": N}` as JSON.

Deployed to `cst8921lab6fn.azurewebsites.net` on a Linux Consumption plan.

Live API verification:
```
$ curl https://cst8921lab6fn.azurewebsites.net/api/visits
{"count": 1}
```
![Screenshot 1](screenshot2.png)


### CORS

**Why the browser blocks the `fetch` without `Access-Control-Allow-Origin`:**

The browser enforces the Same-Origin Policy (SOP): by default, JavaScript in a page at origin A cannot read the response from a request to origin B. The static site is served from `cst8921lab6yh01.z9.web.core.windows.net` (origin A); the Function is at `cst8921lab6fn.azurewebsites.net` (origin B), different origins. Before reading the response, the browser checks whether the server's response includes an `Access-Control-Allow-Origin` header that permits origin A. If not, the browser **discards the response** in the JavaScript runtime, the request still reached the server and got a response, but the calling page's code never sees it.

This is a **browser-enforced** rule, not a server-enforced one. The server receives the request either way; the policy lives entirely in the browser to protect users from malicious scripts reading data from authenticated sessions on other origins. A command-line tool like `curl` ignores CORS because there is no user to protect.

In the Function we return `"Access-Control-Allow-Origin": "*"`, which allows any origin, appropriate for a public read-only counter.

---

## Part G – Azure Front Door

**Subscription limitation:** Azure for Students subscriptions do not permit Azure Front Door resources (`BadRequest: Free Trial and Student account is forbidden for Azure Frontdoor resources`). The commands below are the correct, complete sequence that would be run on a paid subscription, and are included in full for grading purposes.

```bash
WEB_HOST="cst8921lab6yh01.z9.web.core.windows.net"
AZURE_RG="cst8921-lab6-rg"

az afd profile create -g "$AZURE_RG" --profile-name cst8921-afd --sku Standard_AzureFrontDoor

az afd endpoint create -g "$AZURE_RG" --profile-name cst8921-afd --endpoint-name lab6site

az afd origin-group create -g "$AZURE_RG" --profile-name cst8921-afd \
    --origin-group-name og --probe-request-type GET --probe-protocol Https \
    --probe-interval-in-seconds 120 --probe-path / \
    --sample-size 4 --successful-samples-required 3 --additional-latency-in-milliseconds 50

az afd origin create -g "$AZURE_RG" --profile-name cst8921-afd \
    --origin-group-name og --origin-name storage-web \
    --host-name "$WEB_HOST" --origin-host-header "$WEB_HOST" \
    --https-port 443 --priority 1 --weight 1000 --enabled-state Enabled

az afd route create -g "$AZURE_RG" --profile-name cst8921-afd \
    --endpoint-name lab6site --route-name default \
    --origin-group og --supported-protocols Https --https-redirect Enabled \
    --forwarding-protocol HttpsOnly --link-to-default-domain Enabled
```

**Critical origin configuration detail:** The Front Door **origin host must be the static website endpoint** (`<account>.z9.web.core.windows.net`), **not** the blob endpoint (`<account>.blob.core.windows.net`). Pointing at the blob endpoint returns errors because the `$web` virtual container routing lives on the dedicated web endpoint, not the generic blob service.

**Cache purge:**
```bash
az afd endpoint purge -g "$AZURE_RG" --profile-name cst8921-afd \
    --endpoint-name lab6site --content-paths '/*'
```

**Would `no-cache` on HTML eliminate the need to purge?**

With `Cache-Control: no-cache` on `index.html`, a *standards-compliant* CDN must revalidate that asset with the origin on every request before serving it from cache. In theory, you would not need to purge, Front Door would check the origin and serve the new content. However, Azure Front Door has its own caching logic that can sometimes override or supplement origin headers, particularly at the rule-set level. In practice, for a fully fresh deployment it is safer to purge explicitly, since the interaction between Front Door's caching behaviour and origin-supplied headers can vary based on route configuration and overrides. The `no-cache` header reduces stale-serving risk for HTML but does not replace an explicit purge when correctness is critical.

---

## Part H – Idempotent Teardown (`cleanup.py`)

`cleanup.py` calls `check_existence()` before `begin_delete()`, so a second run finds no resource group and exits immediately, it is **idempotent**: the outcome of running it N times is identical to running it once.

**Contrast with `provision.py`:** `provision.py` uses `create_or_update` for the resource group (idempotent by design) but `begin_create` for the storage account. If the account already exists, `begin_create` does **not** error, it returns the existing account, but it re-applies the creation parameters. Whether that is idempotent in practice depends on whether any parameters changed. A second run with identical parameters is safe; a second run with different SKU or settings may fail or produce unexpected results.

**Why declarative IaC tools exist:** Terraform and Bicep describe the *desired state* of infrastructure. The tool computes the diff between desired state and actual state and applies only the changes needed. Idempotency is guaranteed by design, running `terraform apply` twice always converges to the same result. Imperative SDK scripts like `provision.py` must manually reason about current state and implement their own idempotency (as `cleanup.py` does with `check_existence`). For large, multi-resource deployments, hand-rolling that logic becomes error-prone, which is exactly the problem declarative IaC solves.

---

## Analysis Questions

### Q1, Three failure modes that code-first eliminates

1. **Silent configuration drift.** In a manual workflow, an engineer could enable static website hosting in the portal, forget to document it, and a second engineer recreating the environment might miss the setting. Code-first makes every setting explicit and version-controlled in `enable_static_website.py`. The read-back assertion (`get_service_properties()`) catches misconfiguration at deploy time, not during a user-facing outage.

2. **Wrong content types.** The portal's deploy extension guesses MIME types, and historical versions have served HTML as `application/octet-stream`, silently breaking pages. `deploy.py` uses Python's `mimetypes.guess_type()` explicitly and sets `ContentSettings` per blob, making the type deterministic and auditable.

3. **Non-reproducible environments.** A portal-based deployment cannot be replayed on a new subscription or in CI. If the storage account is accidentally deleted, recovery means redoing every click from memory. The code-first approach allows `python provision.py && python enable_static_website.py && python deploy.py` to recreate the entire environment from scratch in minutes, identically.

### Q2, Security and operational reasons for the control-plane / data-plane split

**Security:** Separating the two planes enforces least privilege at a fine grain. An application identity that only needs to read blobs (e.g., a web server) can be given `Storage Blob Data Reader` with no ability to delete the storage account or modify its network rules. A DevOps pipeline that creates infrastructure can be given `Contributor` with no ability to read the business data inside storage accounts. Without the split, any role with infrastructure-creation rights would implicitly get full data access, a significant blast radius if credentials were compromised.

**Operational:** It allows independent rotation and auditing of the two access paths. A data breach on the blob endpoint does not automatically compromise the ability to manage the resource, and vice versa. Azure Policy and Defender for Storage can monitor data-plane activity (blob reads/writes) independently from ARM activity logs.

### Q3, Cache-Control strategy and asset fingerprinting

*(Addressed in Part E above.)* The scenario: `index.html` (served fresh) references `app.js` by a stable name. A user who visited previously has `app.js` cached for one year. On the next deploy, `app.js` changes but its name does not. The user gets the new HTML shell (no-cache revalidates) but the old `app.js` from cache, potentially broken. Prevention: include a content hash in the asset filename (`app.<hash>.js`). Every deploy with changed content produces a new filename, which is never in any cache, forcing a fresh download.

### Q4, What the serverless Function adds and what it costs

**Gains:** The static site shell can be cached aggressively at the edge globally (near-zero latency, near-zero cost at scale) while dynamic data is still fresh on every page load. The Function scales to zero when idle, so there is no always-on server cost for a low-traffic counter. Dynamic logic (database writes, business rules) is kept out of the static bundle and can be updated without redeploying the site.

**New failure modes and costs:**
- **Cold-start latency.** On a Consumption plan, a function that has not been invoked recently takes 1–3 seconds to start. The visit counter appears as "loading…" during this window, which degrades first-impression UX.
- **Additional network hop.** Every page load now makes a cross-origin API call that can fail. If the Function is down or throttled, the counter shows "API unavailable", a visible error that a purely static site would never produce.
- **Table Storage race condition.** The read-modify-write pattern in the counter (`get → increment → update`) is not atomic. Two simultaneous requests can both read the same count and both write it incremented by one, losing a tally. This is addressed in the stretch-goal section.
- **Cost.** While Consumption plan Functions are cheap (first 1M executions/month free), Table Storage, Application Insights, and egress add small but non-zero costs. A purely static site costs essentially nothing to serve from Azure at low traffic.

### Q5, When edge caching hurts correctness

**Scenario:** A product page is cached by Front Door with a 10-minute TTL. An item goes out of stock; the origin updates the page. For up to 10 minutes, Front Door continues serving the cached "in stock" version to users, who click "buy" and are later told the item is unavailable, a frustrating experience and a customer service problem.

**Mitigation without disabling caching entirely:** Use **surrogate keys / cache tags** (if supported by the CDN tier) to allow targeted purges of just the affected resource when inventory changes, rather than purging the entire cache. Alternatively, set a short TTL (60–300 seconds) for content that changes frequently while keeping long TTLs for true static assets. Another approach: serve a static HTML shell from the edge but load inventory availability dynamically via a client-side API call (the Jamstack pattern), the shell is always correct, and the dynamic data bypasses the CDN entirely.

---

## Stretch Goal, Race-Safe Counter (Stretch Goal 2)

The current counter has a read-modify-write race: two simultaneous requests can both read `count=5` and both write `count=6`, losing a visit. The fix uses Azure Table Storage's ETag-based optimistic concurrency:

```python
from azure.core import MatchConditions

@app.route(route="visits", methods=["GET"])
def visits(req: func.HttpRequest) -> func.HttpResponse:
    table = _table()
    while True:
        try:
            entity = table.get_entity(PK, RK)
            entity["count"] = entity["count"] + 1
            table.update_entity(
                entity,
                etag=entity.metadata["etag"],
                match_condition=MatchConditions.IfNotModified,
            )
            break
        except ResourceModifiedError:
            # Another request won the race; retry with fresh entity
            continue
        except ResourceNotFoundError:
            try:
                table.create_entity({"PartitionKey": PK, "RowKey": RK, "count": 1})
                entity = {"count": 1}
                break
            except ResourceExistsError:
                continue  # Lost the creation race; loop back to get

    body = json.dumps({"count": entity["count"]})
    return func.HttpResponse(body, mimetype="application/json",
                             headers={"Access-Control-Allow-Origin": "*"})
```

**How it works:** `update_entity` with `match_condition=MatchConditions.IfNotModified` and the entity's current ETag tells Table Storage to reject the write if the entity changed since we read it. If two requests race, one succeeds and the other receives a `ResourceModifiedError`. The loser retries, reads the updated count, and tries again. Under any concurrency level, every visit is counted exactly once.

---

## Issues Encountered

1. **Zone suffix differs from lab document.** The lab document uses `z13` in the example URL. The actual assigned zone for the `canadacentral` account was `z9`. The `deploy.py` script was updated to read the real endpoint from the management API rather than hardcoding a zone suffix.

2. **Azure Front Door not available on Azure for Students.** Creating the Front Door profile returned `BadRequest: Free Trial and Student account is forbidden for Azure Frontdoor resources`. The full CLI command sequence is documented above and would succeed on a paid subscription. The site is fully functional at the storage web endpoint and the Function API.

3. **RBAC propagation delay.** After assigning `Storage Blob Data Owner`, the first call to `enable_static_website.py` returned 403. A retry loop was used to wait for propagation (~30 seconds in practice).

---

## Deliverables

| File | Purpose |
|---|---|
| `provision.py` | Part B – create RG + storage account via management SDK |
| `enable_static_website.py` | Part C – enable $web hosting + read-back assertion |
| `deploy.py` | Part E – upload site/ with correct content types + cache headers |
| `cleanup.py` | Part H – idempotent resource group deletion |
| `site/index.html` | Front end with visit counter |
| `site/config.js` | API base URL (points at deployed Function) |
| `site/404.html` | Custom 404 page |
| `api/function_app.py` | Azure Function visit counter (Python v2) |
| `api/requirements.txt` | Function dependencies |
| `README.md` | Run order and setup instructions |

**Live endpoints (as of submission):**
- Storage web endpoint: `https://cst8921lab6yh01.z9.web.core.windows.net/`
- Function API: `https://cst8921lab6fn.azurewebsites.net/api/visits`
