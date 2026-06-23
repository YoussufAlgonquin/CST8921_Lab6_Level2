import os
import json
import azure.functions as func
from azure.data.tables import TableServiceClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

CONN = os.environ["AzureWebJobsStorage"]
TABLE = "visits"
PK, RK = "site", "counter"


def _table():
    svc = TableServiceClient.from_connection_string(CONN)
    svc.create_table_if_not_exists(TABLE)
    return svc.get_table_client(TABLE)


@app.route(route="visits", methods=["GET"])
def visits(req: func.HttpRequest) -> func.HttpResponse:
    table = _table()
    try:
        entity = table.get_entity(PK, RK)
        entity["count"] = entity["count"] + 1
        table.update_entity(entity)
    except Exception:
        entity = {"PartitionKey": PK, "RowKey": RK, "count": 1}
        table.create_entity(entity)

    body = json.dumps({"count": entity["count"]})
    return func.HttpResponse(
        body,
        mimetype="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
    )
