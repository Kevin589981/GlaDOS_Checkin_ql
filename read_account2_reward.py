import json, math, os
from datetime import datetime, timezone
import requests
from checkin import GlaDOSCheckin
from session_cookies import split_accounts, mask_cookie

def num(value):
    try:
        v=float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None

def date(value):
    try:
        if isinstance(value,str) and "-" in value:
            return datetime.fromisoformat(value.replace("Z","+00:00")).isoformat()
        v=float(value)
        return datetime.fromtimestamp(v/1000 if v>1e11 else v, timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None

try:
    cookies=split_accounts(os.environ.get("GR_COOKIE",""))
    client=GlaDOSCheckin(cookies)
    mask_cookie(cookies[1])
    r=requests.get(client.origin+"/api/user/points",headers=client.headers(cookies[1],client.useragents[1]),timeout=25,allow_redirects=False)
    body=client.response_data(r)
    if body.get("code")!=0:raise ValueError("denied")
    history=body.get("history") or []
    records=[{"time":date(x.get("time")),"change":num(x.get("change"))} for x in history if isinstance(x,dict) and "checkin" in str(x.get("business","")).lower()][:5]
    print(json.dumps({"points_type":type(body.get("points")).__name__,"streak":num(body.get("streak")),"recent_checkin_records":records}))
except Exception as e:
    print("Read-only diagnosis failed:",type(e).__name__)
    raise SystemExit(1)
