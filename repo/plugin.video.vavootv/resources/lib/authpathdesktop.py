def getAuthSignature():
    """
    Get authentication signature from Vavoo API.
    Caches the signature for AUTH_CACHE_TTL seconds to avoid redundant requests.
    Returns None and shows error dialog on failure.
    """
    global _auth_cache

    # Return cached signature if still valid
    if _auth_cache["signature"] and time.time() < _auth_cache["expires"]:
        log_debug("Using cached auth signature", "getAuthSignature")
        return _auth_cache["signature"]
    
    log_debug("Requesting fresh auth signature...", "getAuthSignature")
    
    # Use Electron (desktop Vavoo app) user-agent - this is what working proxies use
    headers = {
        "accept": "*/*",
        "user-agent": "electron-fetch/1.0 electron (+https://github.com/arantes555/electron-fetch)",
        "Accept-Language": "de",
        "Accept-Encoding": "gzip, deflate",
        "content-type": "application/json; charset=utf-8",
        "Connection": "close"
    }
    
    import uuid as _uuid
    unique_id = _uuid.uuid4().hex[:16]
    
    # Standard Vavoo Auth Payload
    data = {
        "token": "8Us2TfjeOFrzqFFTEjL3E5KfdAWGa5PV3wQe60uK4BmzlkJRMYFu0ufaM_eeDXKS2U04XUuhbDTgGRJrJARUwzDyCcRToXhW5AcDekfFMfwNUjuieeQ1uzeDB9YWyBL2cn5Al3L3gTnF8Vk1t7rPwkBob0swvxA",
        "reason": "player.enter",
        "locale": "de",
        "theme": "dark",
        "metadata": {
            "device": {
                "type": "Desktop",
                "brand": "Unknown",
                "model": "Unknown",
                "name": "Unknown",
                "uniqueId": unique_id
            },
            "os": {
                "name": "windows",
                "version": "10.0.22631",
                "abis": [],
                "host": "electron"
            },
            "app": {
                "platform": "electron",
                "version": "3.1.4",
                "buildId": "288045000",
                "engine": "jsc",
                "signatures": [],
                "installer": "unknown"
            },
            "version": {
                "package": "tv.vavoo.app",
                "binary": "3.1.4",
                "js": "3.1.4"
            }
        },
        "appFocusTime": 27229,
        "playerActive": True,
        "playDuration": 0,
        "devMode": False,
        "hasAddon": False,
        "castConnected": False,
        "package": "tv.vavoo.app",
        "version": "3.1.4",
        "process": "app",
        "firstAppStart": int(time.time() * 1000) - 86400000,
        "lastAppStart": int(time.time() * 1000),
        "ipLocation": "",
        "adblockEnabled": False,
        "proxy": {
            "supported": ["ss"],
            "engine": "ss",
            "enabled": False,
            "autoServer": True,
            "id": "ca-bhs"
        },
        "iap": {"supported": True}
    }
    
    try:
        log_debug(f"POST {AUTH_API_URL}", "getAuthSignature")
        response = requests.post(AUTH_API_URL, json=data, headers=headers, timeout=10)
        log_debug(f"Response status: {response.status_code}", "getAuthSignature")
        
        result = response.json()
        
        # Log the full response for debugging (helps diagnose watermark/auth issues)
        # log(f"Auth ping full response: {json.dumps(result, indent=2)}", "getAuthSignature", force=True)
        
        signature = result.get("addonSig")

        if signature:
            log_debug("Auth signature obtained successfully", "getAuthSignature")
            
            # Decode and log signature data to check status
            # try:
                # import base64
                # sig_data = json.loads(base64.b64decode(signature + '=='))
                # inner = json.loads(sig_data.get("data", "{}"))
                # log(f"Auth status: status={inner.get('status')}, verified={inner.get('verified')}, app_ok={inner.get('app', {}).get('ok')}", "getAuthSignature", force=True)
            # except Exception:
                # pass
            
            _auth_cache["signature"] = signature
            _auth_cache["expires"] = time.time() + AUTH_CACHE_TTL
            return signature
        else:
            # log(f"No addonSig in response: {result}", "getAuthSignature", force=True)
            # error_dialog("Authentication Failed", "Failed to get auth signature from server.")
            return None

    # except requests.exceptions.Timeout:
    #     log("Auth request timed out", "getAuthSignature", force=True)
    #     log_exception("getAuthSignature")
    #     error_dialog("Authentication Failed", "Request timed out. Please check your internet connection.")
    #     return None
    # except requests.exceptions.RequestException as e:
    #     log(f"Auth request failed: {e}", "getAuthSignature", force=True)
    #     log_exception("getAuthSignature")
    #     error_dialog("Authentication Failed", f"Network error: {str(e)}")
    #     return None
    # except Exception as e:
    #     log(f"Unexpected auth error: {e}", "getAuthSignature", force=True)
    #     log_exception("getAuthSignature")
    #     error_dialog("Authentication Failed", f"Unexpected error: {str(e)}")
    #     return None

    except:
        pass
    return None