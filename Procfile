# Railway (and other Procfile-aware hosts) run this to start the web console.
# $PORT is supplied by the platform; TLS is terminated at the platform edge,
# so the app itself serves plain HTTP internally but is reachable over HTTPS.
web: uvicorn webconsole:app --host 0.0.0.0 --port $PORT
