import urllib.request

req = urllib.request.Request(
    "http://localhost:8000/v1/chat/completions",
    headers={"Authorization": "Bearer dummy", "Content-Type": "application/json"},
)
req.method = "POST"
# We can't do this easily since the server is shutting down.
