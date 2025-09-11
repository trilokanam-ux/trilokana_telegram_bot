import json

with open("credentials.json", "r") as f:
    creds = json.load(f)

# Convert to single-line JSON
single_line = json.dumps(creds)

print(single_line)
